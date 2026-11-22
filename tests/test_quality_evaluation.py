"""Testes sintéticos; não constituem calibração humana realizada."""
import unittest

from quality_evaluation import evaluate


class EvaluationTests(unittest.TestCase):
    def test_metricas_multiclasse_e_baseline_majoritario(self):
        rows = [
            {"expected": "a", "predicted": "a", "score": .8},
            {"expected": "a", "predicted": "b", "score": .7},
            {"expected": "b", "predicted": "b", "score": .6},
        ]
        result = evaluate(rows, labels=["a", "b", "c"])
        self.assertEqual(result["confusion_matrix"]["a"]["b"], 1)
        self.assertEqual(result["per_class"]["a"], {
            "precision": 1., "recall": .5, "f1": 2 / 3, "support": 2})
        self.assertEqual(result["per_class"]["c"]["f1"], 0.)
        self.assertAlmostEqual(result["macro_f1"], 4 / 9)
        self.assertAlmostEqual(result["accuracy"], 2 / 3)
        self.assertEqual(result["majority_class"], "a")
        self.assertEqual(result["distribution"], {"a": 2, "b": 1, "c": 0})
        self.assertIsNone(result["brier"])
        self.assertIsNone(result["ece"])
        self.assertEqual(result["calibration_reason"], "score_not_calibrated")

    def test_abstencao_unknown_e_curva_com_empates(self):
        rows = [
            {"expected": "a", "predicted": "a", "score": .8},
            {"expected": "b", "predicted": "a", "score": .8},
            {"expected": "a", "predicted": "indeterminado", "score": .9},
            {"expected": "indeterminado", "predicted": "a", "score": .9},
            {"expected": "b", "predicted": "b", "score": None},
        ]
        result = evaluate(rows, labels=["a", "b"])
        self.assertEqual(result["sample_count"], 5)
        self.assertEqual(result["evaluated_count"], 4)
        self.assertEqual(result["unknown_expected_count"], 1)
        self.assertEqual(result["accuracy"], .5)
        self.assertEqual(result["abstention"]["count"], 1)
        self.assertEqual(result["abstention"]["coverage"], .75)
        self.assertAlmostEqual(result["abstention"]["precision"], 2 / 3)
        self.assertEqual(result["abstention"]["curve"], [
            {"threshold": .8, "accepted": 2, "coverage": .5, "precision": .5}])
        self.assertEqual(result["confusion_matrix"]["indeterminado"]["a"], 1)

    def test_amostra_vazia_nao_fabrica_metricas(self):
        result = evaluate([], labels=["a", "b"])
        for key in ("accuracy", "macro_f1", "majority_class", "brier", "ece"):
            self.assertIsNone(result[key])
        self.assertEqual(result["metrics_reason"], "empty_sample")
        self.assertIsNone(result["abstention"]["coverage"])

    def test_probabilidade_explicita_mede_correcao_nao_multiclasse(self):
        rows = [{"expected": "a", "predicted": "a", "score": .8},
                {"expected": "b", "predicted": "a", "score": .6}]
        result = evaluate(rows, labels=["a", "b"], score_type="calibrated_probability")
        self.assertAlmostEqual(result["brier"], .2)
        self.assertAlmostEqual(result["ece"], .4)
        self.assertIsNone(result["calibration_reason"])
        rows[1]["score"] = None
        missing = evaluate(rows, labels=["a", "b"], score_type="calibrated_probability")
        self.assertIsNone(missing["brier"])
        self.assertIsNone(missing["ece"])
        self.assertEqual(missing["calibration_reason"], "missing_scores")
        empty = evaluate([], labels=["a"], score_type="calibrated_probability")
        self.assertEqual(empty["calibration_reason"], "no_accepted_predictions")

    def test_validacao_rigorosa_sem_eco_dos_dados(self):
        base = {"expected": "a", "predicted": "a", "score": .5}
        cases = [
            ([base], {"labels": "a"}, "invalid_labels"),
            ([base], {"labels": []}, "invalid_labels"),
            ([base], {"labels": ["a", "a"]}, "invalid_labels"),
            ([base], {"labels": ["a", 1]}, "invalid_labels"),
            ([base], {"labels": [""]}, "invalid_labels"),
            ([base], {"labels": ["indeterminado"]}, "invalid_labels"),
            ([base], {"labels": ["a"], "score_type": "privado"}, "invalid_score_type"),
            ([base], {"labels": ["a"], "score_type": []}, "invalid_score_type"),
            (None, {"labels": ["a"]}, "invalid_pairs"),
            ("privado", {"labels": ["a"]}, "invalid_pairs"),
            ({}, {"labels": ["a"]}, "invalid_pairs"),
            ([None], {"labels": ["a"]}, "invalid_pair"),
            ([{"expected": "a", "predicted": "a"}], {"labels": ["a"]}, "invalid_pair"),
            ([dict(base, extra="privado")], {"labels": ["a"]}, "invalid_pair"),
            ([dict(base, expected="privado")], {"labels": ["a"]}, "invalid_label"),
            ([dict(base, predicted=[])], {"labels": ["a"]}, "invalid_label"),
        ]
        for score in (True, 1, "privado", float("nan"), float("inf"), -float("inf")):
            cases.append(([dict(base, score=score)], {"labels": ["a"]}, "invalid_score"))
        for score in (-.01, 1.01):
            cases.append(([dict(base, score=score)], {"labels": ["a"], "score_type": "calibrated_probability"}, "invalid_score"))
        for index, (rows, kwargs, code) in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(ValueError) as caught:
                    evaluate(rows, **kwargs)
                self.assertEqual(str(caught.exception), code)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(evaluate([dict(base, score=-2.)], labels=["a"])["accuracy"], 1.)

    def test_concordancia_e_kappa(self):
        from quality_evaluation import inter_reviewer_agreement
        pairs = [{"reviewer_a": a, "reviewer_b": b} for a, b in
                 [("a", "a"), ("a", "a"), ("a", "b"), ("b", "b")]]
        result = inter_reviewer_agreement(pairs)
        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["observed_agreement"], .75)
        self.assertEqual(result["cohen_kappa"], .5)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["reason"])

    def test_limites_calibracao_e_bin_compartilhado(self):
        rows = [{"expected": "a", "predicted": "a", "score": .51},
                {"expected": "b", "predicted": "a", "score": .59},
                {"expected": "a", "predicted": "a", "score": 1.},
                {"expected": "a", "predicted": "b", "score": 0.}]
        result = evaluate(rows, labels=["a", "b"], score_type="calibrated_probability")
        self.assertAlmostEqual(result["brier"], .14705)
        self.assertAlmostEqual(result["ece"], .025)
        self.assertEqual([p["threshold"] for p in result["abstention"]["curve"]], [1., .59, .51, 0.])

    def test_apenas_unknown_e_apenas_abstencao(self):
        unknown = evaluate([{"expected": "indeterminado", "predicted": "a", "score": None}], labels=["a"])
        self.assertEqual(unknown["metrics_reason"], "no_known_expected")
        self.assertIsNone(unknown["accuracy"])
        self.assertIsNone(unknown["macro_f1"])
        abstain = evaluate([{"expected": "a", "predicted": "indeterminado", "score": .9}], labels=["a"])
        self.assertEqual(abstain["accuracy"], 0.)
        self.assertEqual(abstain["per_class"]["a"]["recall"], 0.)
        self.assertEqual(abstain["abstention"]["coverage"], 0.)
        self.assertIsNone(abstain["abstention"]["precision"])
        self.assertEqual(abstain["abstention"]["curve"], [])

    def test_iteraveis_sem_mutacao_e_saida_json_finita(self):
        import copy
        import json
        rows = [{"expected": "b", "predicted": "a", "score": .7},
                {"expected": "a", "predicted": "a", "score": .7}]
        saved = copy.deepcopy(rows)
        labels = ["b", "a"]
        result = evaluate(iter(rows), labels=labels)
        self.assertEqual(rows, saved)
        self.assertEqual(labels, ["b", "a"])
        self.assertEqual(result["majority_class"], "b")
        self.assertEqual(result, json.loads(json.dumps(result, allow_nan=False)))

    def test_kappa_negativo_e_unknown_como_categoria(self):
        from quality_evaluation import inter_reviewer_agreement
        result = inter_reviewer_agreement(iter([
            {"reviewer_a": "a", "reviewer_b": "indeterminado"},
            {"reviewer_a": "indeterminado", "reviewer_b": "a"}]))
        self.assertEqual(result["observed_agreement"], 0.)
        self.assertEqual(result["cohen_kappa"], -1.)

    def test_concordancia_desconhecida_e_validacao(self):
        from quality_evaluation import inter_reviewer_agreement
        empty = inter_reviewer_agreement([])
        self.assertEqual(empty["status"], "unknown")
        self.assertEqual(empty["reason"], "empty_sample")
        self.assertIsNone(empty["observed_agreement"])
        self.assertIsNone(empty["cohen_kappa"])
        constant = inter_reviewer_agreement([{"reviewer_a": "a", "reviewer_b": "a"}])
        self.assertEqual(constant["observed_agreement"], 1.)
        self.assertIsNone(constant["cohen_kappa"])
        self.assertEqual(constant["reason"], "degenerate_marginals")
        self.assertEqual(constant["status"], "unknown")
        # Margem constante de apenas um revisor também é degenerada.
        one_constant = inter_reviewer_agreement([
            {"reviewer_a": "a", "reviewer_b": "a"},
            {"reviewer_a": "a", "reviewer_b": "b"}])
        self.assertIsNone(one_constant["cohen_kappa"])
        self.assertEqual(one_constant["observed_agreement"], .5)
        for index, rows in enumerate([
            [{"reviewer_a": [], "reviewer_b": "a"}],
            [{"reviewer_a": "a", "reviewer_b": " "}],
            [{"reviewer_a": 1, "reviewer_b": "a"}]]):
            with self.subTest(case=index), self.assertRaises(ValueError) as caught:
                inter_reviewer_agreement(rows)
            self.assertEqual(str(caught.exception), "invalid_label")
        with self.assertRaisesRegex(ValueError, "^invalid_pair$"):
            inter_reviewer_agreement([{"reviewer_a": "a"}])


if __name__ == "__main__":
    unittest.main()
