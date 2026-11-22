"""Offline contracts with synthetic events and an inference-boundary double."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import quality_classifier


def event(**changes):
    return dict({'event_id': 'event-original', 'tenant_id': 'tenant-original',
                 'source_id': 'source-original', 'session_id': 'session-original',
                 'task_id': 'task-original', 'event_type': 'intervention',
                 'timestamp': 123, 'actor': 'user',
                 'text': 'Você usou o requisito errado; corrija para o combinado.'}, **changes)


class Client:
    base_url = 'https://synthetic.invalid/api'

    def __init__(self, labels=('sim',)):
        self.labels = iter(labels)
        self.calls = []

    def classify(self, model, state, questions):
        self.calls.append((model, json.loads(state), questions))
        label = next(self.labels)
        return {'model': model, 'answers': {'classificacao': {
            'type': 'choice', 'confidence': 1,
            'choice': label, 'probabilities': {
                key: int(key == label) for key in questions['classificacao']['criteria']}}}}


class ClassifierTests(unittest.TestCase):
    def test_user_correction_is_provisional_with_original_input_anchor(self):
        events = [event()]
        before = copy.deepcopy(events)
        client = Client()
        with tempfile.TemporaryDirectory() as temporary:
            labels = quality_classifier.classify_events(events, client, 'synthetic-model', temporary)
            self.assertEqual(len(labels), 1)
            label = labels[0]
            self.assertEqual(label, {
                'source_id': 'source-original', 'event_id': 'event-original',
                'task_id': 'task-original', 'label_name': 'explicit_user_correction',
                'label_value': 'sim', 'classifier_score_raw': 1,
                'score_type': 'model_class_distribution_uncalibrated',
                'evidence_event_ids': ['event-original'],
                'evidence_scope': 'input_event_reference_only',
                'origin': 'classifier_inference', 'is_observable': False,
                'review_required': True, 'unknown_reason': None,
                'model_id': 'synthetic-model', 'prompt_version': 1,
                'classifier_version': 'quality-classifier-v1', 'schema_version': 1})
            self.assertTrue((Path(temporary) / 'quality_correction' / 'decisions.sqlite').is_file())
        self.assertEqual(events, before)
        self.assertEqual(len(client.calls), 1)
        state = client.calls[0][1]
        self.assertEqual(state['texto'], events[0]['text'])
        self.assertLessEqual(len(state['contexto']), 1200)
        self.assertEqual(state['provenance'], [{key: events[0][key] for key in
                         ('tenant_id', 'source_id', 'session_id', 'event_id', 'task_id', 'event_type', 'timestamp', 'actor')}])

    def test_malformed_response_abstains_and_resume_never_retries(self):
        class Malformed(Client):
            def classify(self, model, state, questions):
                self.calls.append((model, json.loads(state), questions))
                return {'model': model, 'answers': {'classificacao': {
                    'choice': 'sim', 'probabilities': {'sim': 0.999}}}}

        events = [event()]
        client = Malformed()
        with tempfile.TemporaryDirectory() as temporary:
            labels = quality_classifier.classify_events(events, client, 'synthetic-model', temporary)
            self.assertEqual(labels[0]['label_value'], 'indeterminado')
            self.assertIsNone(labels[0]['classifier_score_raw'])
            self.assertEqual(labels[0]['unknown_reason'], 'classification_failed')
            self.assertTrue(labels[0]['review_required'])
            self.assertFalse(labels[0]['is_observable'])
            self.assertEqual(len(client.calls), 1)
            resumed = Client()
            self.assertEqual(quality_classifier.classify_events(events, resumed, 'synthetic-model', temporary), labels)
            self.assertEqual(resumed.calls, [])

    def test_conflicting_high_scores_never_modify_events_or_create_evidence(self):
        events = [event(text='a' * 2400 + 'b')]
        before = copy.deepcopy(events)
        client = Client(('sim', 'nao'))
        with tempfile.TemporaryDirectory() as temporary:
            labels = quality_classifier.classify_events(events, client, 'synthetic-model', temporary)
        self.assertEqual(labels[0]['label_value'], 'indeterminado')
        self.assertIsNone(labels[0]['classifier_score_raw'])
        self.assertEqual(labels[0]['unknown_reason'], 'conflicting_chunk_labels')
        self.assertEqual(events, before)
        self.assertEqual(labels[0]['evidence_event_ids'], ['event-original'])
        self.assertTrue(labels[0]['review_required'])
        self.assertFalse(labels[0]['is_observable'])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(''.join(call[1]['texto'] for call in client.calls), events[0]['text'])

    def test_assistant_delivery_outcome_is_inference_not_resolved_event(self):
        events = [event(event_id='delivery', actor='assistant', event_type='delivery',
                        text='O teste sintético retornou exit 0; segue a entrega.')]
        before = copy.deepcopy(events)
        client = Client(('resolvida_com_evidencia',))
        with tempfile.TemporaryDirectory() as temporary:
            labels = quality_classifier.classify_events(events, client, 'synthetic-model', temporary)
            self.assertEqual(len(labels), 1)
            self.assertEqual(labels[0]['label_name'], 'outcome')
            self.assertEqual(labels[0]['label_value'], 'resolvida_com_evidencia')
            self.assertEqual(labels[0]['classifier_score_raw'], 1)
            self.assertFalse(labels[0]['is_observable'])
            self.assertTrue(labels[0]['review_required'])
            self.assertTrue((Path(temporary) / 'quality_outcome' / 'decisions.sqlite').is_file())
            resumed = Client()
            self.assertEqual(quality_classifier.classify_events(events, resumed, 'synthetic-model', temporary), labels)
            self.assertEqual(resumed.calls, [])
        self.assertEqual(events, before)

    def test_absent_or_ineligible_text_does_not_become_negative_label(self):
        events = [event(text=None), event(text='  '), event(text=123),
                  event(actor='tool'), event(actor='system'), event(actor=None)]
        events.append({key: value for key, value in event().items() if key != 'text'})
        client = Client()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'unused'
            self.assertEqual(quality_classifier.classify_events(events, client, 'synthetic-model', output), [])
            self.assertFalse(output.exists())
        self.assertEqual(client.calls, [])

    def test_success_resume_zero_calls_for_both_rubrics_and_no_foreign_context(self):
        events = [event(), event(event_id='assistant', actor='assistant', event_type='attempt',
                                 text='Ainda falta executar os testes.')]
        before = copy.deepcopy(events)
        with tempfile.TemporaryDirectory() as temporary:
            first = Client(('nao', 'parcialmente_resolvida'))
            labels = quality_classifier.classify_events(iter(events), first, 'synthetic-model', temporary)
            self.assertEqual([label['label_name'] for label in labels], ['explicit_user_correction', 'outcome'])
            for index, call in enumerate(first.calls):
                self.assertEqual(call[1]['texto'], events[index]['text'])
                self.assertEqual(call[1]['contexto'], '')
                self.assertTrue(call[1]['context_missing'])
                self.assertEqual(call[1]['provenance'][0]['event_id'], events[index]['event_id'])
            resumed = Client()
            self.assertEqual(quality_classifier.classify_events(events, resumed, 'synthetic-model', temporary), labels)
            self.assertEqual(resumed.calls, [])
        self.assertEqual(events, before)

    def test_multiple_unanimous_chunks_have_no_fabricated_single_label_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = Client(('sim', 'sim'))
            labels = quality_classifier.classify_events([event(text='a' * 2401)], client, 'synthetic-model', temporary)
        self.assertEqual(labels[0]['label_value'], 'sim')
        self.assertIsNone(labels[0]['classifier_score_raw'])
        self.assertEqual(labels[0]['unknown_reason'], 'multiple_chunks_no_single_label_score')

    def test_single_chunk_abstention_keeps_raw_distribution_not_accuracy(self):
        with tempfile.TemporaryDirectory() as temporary:
            labels = quality_classifier.classify_events([event()], Client(('indeterminado',)), 'synthetic-model', temporary)
        self.assertEqual(labels[0]['label_value'], 'indeterminado')
        self.assertEqual(labels[0]['classifier_score_raw'], 1)
        self.assertEqual(labels[0]['unknown_reason'], 'model_abstention')
        self.assertEqual(labels[0]['score_type'], 'model_class_distribution_uncalibrated')
        self.assertTrue(labels[0]['review_required'])

    def test_failed_outcome_is_indeterminada_not_success_and_terminal(self):
        class Failed(Client):
            def classify(self, model, state, questions):
                self.calls.append((model, json.loads(state), questions))
                raise RuntimeError('synthetic transport failure')

        events = [event(actor='assistant', event_type='delivery')]
        with tempfile.TemporaryDirectory() as temporary:
            client = Failed()
            labels = quality_classifier.classify_events(events, client, 'synthetic-model', temporary)
            self.assertEqual(labels[0]['label_value'], 'indeterminada')
            self.assertIsNone(labels[0]['classifier_score_raw'])
            self.assertEqual(labels[0]['unknown_reason'], 'classification_failed')
            self.assertEqual(len(client.calls), 1)
            resumed = Client()
            self.assertEqual(quality_classifier.classify_events(events, resumed, 'synthetic-model', temporary), labels)
            self.assertEqual(resumed.calls, [])

    def test_partial_chunk_failure_overrides_high_success_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            # Second label is invalid for this rubric, after a high-score success.
            labels = quality_classifier.classify_events([event(text='a' * 2401)], Client(('sim', 'invalid')), 'synthetic-model', temporary)
        self.assertEqual(labels[0]['label_value'], 'indeterminado')
        self.assertEqual(labels[0]['unknown_reason'], 'classification_failed')
        self.assertIsNone(labels[0]['classifier_score_raw'])

    def test_original_identity_distinguishes_sources_and_unknown_task_stays_unknown(self):
        events = [event(task_id=None), event(source_id='other-source', task_id=None)]
        with tempfile.TemporaryDirectory() as temporary:
            client = Client(('sim', 'nao'))
            labels = quality_classifier.classify_events(events, client, 'synthetic-model', temporary)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual([label['source_id'] for label in labels], ['source-original', 'other-source'])
        self.assertTrue(all(label['task_id'] is None for label in labels))
        self.assertTrue(all(label['evidence_event_ids'] == ['event-original'] for label in labels))

    def test_changed_campaign_rejected_without_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            quality_classifier.classify_events([event()], Client(), 'synthetic-model', temporary)
            client = Client()
            with self.assertRaisesRegex(ValueError, '^campaign_mismatch$'):
                quality_classifier.classify_events([event(text='Outro texto autorizado.')], client, 'synthetic-model', temporary)
            self.assertEqual(client.calls, [])

    def test_lost_entire_rubric_checkpoint_blocks_before_any_inference(self):
        import shutil
        events = [event(), event(event_id='delivery', actor='assistant', event_type='delivery')]
        for rubric in ('quality_correction', 'quality_outcome'):
            with tempfile.TemporaryDirectory() as temporary:
                quality_classifier.classify_events(events, Client(('sim', 'nao_resolvida')),
                                                   'synthetic-model', temporary)
                lost = Path(temporary) / rubric
                shutil.rmtree(lost)
                before = {p.relative_to(temporary): p.read_bytes()
                          for p in Path(temporary).rglob('*') if p.is_file()}
                resumed = Client(('sim', 'nao_resolvida'))
                with self.assertRaisesRegex(ValueError, '^checkpoint_incomplete$'):
                    quality_classifier.classify_events(events, resumed, 'synthetic-model', temporary)
                self.assertEqual(resumed.calls, [])
                self.assertFalse(lost.exists())
                self.assertEqual(before, {p.relative_to(temporary): p.read_bytes()
                                         for p in Path(temporary).rglob('*') if p.is_file()})

    def test_missing_checkpoint_not_recreated_or_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            quality_classifier.classify_events([event()], Client(), 'synthetic-model', temporary)
            directory = Path(temporary) / 'quality_correction'
            (directory / 'manifest.json').unlink()
            before = {path.name: path.read_bytes() for path in directory.iterdir()}
            client = Client()
            with self.assertRaisesRegex(ValueError, '^checkpoint_incomplete$'):
                quality_classifier.classify_events([event()], client, 'synthetic-model', temporary)
            self.assertEqual(client.calls, [])
            self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})


if __name__ == '__main__':
    unittest.main()
