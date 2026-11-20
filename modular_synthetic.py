"""Handwritten synthetic smoke cases; never load a user profile."""


def cases(rubric_id):
    if rubric_id == 'domain':
        from synthetic import CASES, items
        return list(zip(items(), (case[0] for case in CASES)))
    if rubric_id != 'feedback':
        raise ValueError('unsupported_verification_rubric')
    examples = [
        ('correcao_redirecionamento', 'Não foi o que pedi. Refaça a lista ordenando por prioridade.', 'Segue a lista ordenada alfabeticamente.'),
        ('insatisfacao', 'Essa resposta foi muito ruim e não me ajudou.', 'Aqui está minha resposta à sua dúvida.'),
        ('confirmacao_positiva', 'Agora sim, está correto. Era exatamente o que eu precisava.', 'Corrigi a lista na ordem solicitada.'),
        ('neutro', 'Mudando de assunto: qual a diferença entre uma estrela e um planeta?', 'Terminamos a lista anterior.'),
        ('indeterminado', 'Aquilo de lá.', ''),
    ]
    return [({'id': 'synthetic-feedback-' + str(index), 'kind': 'feedback', 'text': text,
              'context': context, 'context_missing': not bool(context), 'context_truncated': False,
              'delegated': False, 'provenance': [{'source': 'synthetic'}]}, expected)
            for index, (expected, text, context) in enumerate(examples)]
