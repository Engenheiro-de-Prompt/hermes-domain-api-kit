"""Métricas determinísticas para revisão humana offline, sem inferência ou E/S."""

from collections.abc import Mapping
import math

UNKNOWN = "indeterminado"


def inter_reviewer_agreement(pairs) -> dict:
    """Concordância nominal; qualquer string não vazia é categoria válida.

    ``indeterminado`` é categoria explícita aqui, não dado ausente.
    Sem amostra, ambas as métricas são nulas. Se qualquer revisor só usa
    uma categoria, kappa é conservadoramente desconhecido, mesmo quando
    a fórmula produziria zero; a concordância observada é preservada.
    """
    rows = _rows(pairs, {"reviewer_a", "reviewer_b"})
    n = len(rows)
    if not n:
        return dict(sample_count=0, observed_agreement=None, cohen_kappa=None,
                    status="unknown", reason="empty_sample")
    counts_a = {}
    counts_b = {}
    for row in rows:
        a, b = row["reviewer_a"], row["reviewer_b"]
        if any(type(value) is not str or not value.strip() for value in (a, b)):
            raise QualityEvaluationError("invalid_label")
        counts_a[a] = counts_a.get(a, 0) + 1
        counts_b[b] = counts_b.get(b, 0) + 1
    observed = sum(r["reviewer_a"] == r["reviewer_b"] for r in rows) / n
    if len(counts_a) < 2 or len(counts_b) < 2:
        return dict(sample_count=n, observed_agreement=observed, cohen_kappa=None,
                    status="unknown", reason="degenerate_marginals")
    expected = sum(counts_a[a] * counts_b.get(a, 0) for a in counts_a) / (n * n)
    return dict(sample_count=n, observed_agreement=observed,
                cohen_kappa=(observed - expected) / (1 - expected), status="ok", reason=None)


class QualityEvaluationError(ValueError):
    """Erro público com código fixo, sem valores nem conteúdo das entradas."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _rows(pairs, fields):
    """Materializa iterável e valida o esquema fechado de cada par."""
    if isinstance(pairs, (str, bytes, bytearray, Mapping)):
        raise QualityEvaluationError("invalid_pairs")
    try:
        rows = list(pairs)
    except Exception:
        raise QualityEvaluationError("invalid_pairs") from None
    for row in rows:
        if type(row) is not dict or set(row) != fields:
            raise QualityEvaluationError("invalid_pair")
    return rows


def evaluate(pairs, *, labels, score_type="uncalibrated") -> dict:
    """Avalia classes; ``indeterminado`` é reservado para desconhecido/abstenção.

    A matriz inclui todos os pares (linhas esperadas, colunas previstas).
    Gabaritos desconhecidos ficam fora dos denominadores das métricas.
    Abstenções com gabarito conhecido contam como erros e falsos negativos.
    Classes sem suporte têm métricas zero; macro inclui todas as classes.
    Empates da maioria seguem a ordem de ``labels``; distribuição é contagem.
    A curva aceita score >= limiar, agrupa empates e exclui scores ausentes;
    sua cobertura usa todos os gabaritos conhecidos como denominador.
    A cobertura geral inclui previsões determinadas com score ausente.

    ``pairs`` é iterável de dicionários fechados com expected/predicted/score.
    ``labels`` é lista/tupla não vazia de strings únicas; não deve incluir o
    marcador reservado. Outros rótulos fora desse enum são erros, não remapeados.
    Score é estritamente float finito ou None (int/bool não são aceitos).
    ``uncalibrated`` admite qualquer float finito e permite somente ordenar.

    Somente ``calibrated_probability`` habilita Brier e ECE. Nesse modo,
    score representa P(previsão correta), entre 0 e 1: Brier é binário sobre
    o indicador de acerto, NÃO o Brier multiclasse de um vetor de probabilidades.
    ECE usa dez intervalos de largura 0,1, fechados à esquerda, último inclui 1.
    Ambos usam apenas gabaritos conhecidos/previsões não abstidas; se faltar
    qualquer score nesse conjunto, ambos ficam None com missing_scores.
    Ausência de previsões aceitas usa no_accepted_predictions; escores não
    declarados calibrados usam score_not_calibrated. Declarar o tipo NÃO
    realiza calibração, nem comprova revisão humana ou qualidade do modelo.

    Sem gabarito conhecido, accuracy/macro_f1/majority_class ficam None com
    metrics_reason. Na abstenção, precision é taxa de acerto entre aceitos,
    não média de precisão por classe; None recebe motivo em reason.
    Erros são QualityEvaluationError (ValueError), com código fixo em code
    e na mensagem: invalid_labels, invalid_score_type, invalid_pairs,
    invalid_pair, invalid_label ou invalid_score. Nenhum dado é incluído.
    """
    if type(labels) not in (list, tuple) or not labels:
        raise QualityEvaluationError("invalid_labels")
    if any(type(label) is not str or not label.strip() or label == UNKNOWN for label in labels):
        raise QualityEvaluationError("invalid_labels")
    if len(set(labels)) != len(labels):
        raise QualityEvaluationError("invalid_labels")
    if type(score_type) is not str or score_type not in ("uncalibrated", "calibrated_probability"):
        raise QualityEvaluationError("invalid_score_type")
    labels = list(labels)
    rows = _rows(pairs, {"expected", "predicted", "score"})
    axes = labels + [UNKNOWN]
    for row in rows:
        for field in ("expected", "predicted"):
            if type(row[field]) is not str or row[field] not in axes:
                raise QualityEvaluationError("invalid_label")
        score = row["score"]
        if score is not None and (type(score) is not float or not math.isfinite(score)):
            raise QualityEvaluationError("invalid_score")
        if score_type == "calibrated_probability" and score is not None and not 0 <= score <= 1:
            raise QualityEvaluationError("invalid_score")
    matrix = {a: {b: 0 for b in axes} for a in axes}
    for row in rows:
        matrix[row["expected"]][row["predicted"]] += 1
    known = [r for r in rows if r["expected"] != UNKNOWN]
    accepted = [r for r in known if r["predicted"] != UNKNOWN]
    n = len(known)
    distribution = {a: sum(matrix[a].values()) for a in labels}
    per_class = {}
    for a in labels:
        tp = matrix[a][a]
        support = distribution[a]
        predicted = sum(matrix[b][a] for b in labels)
        per_class[a] = dict(
            precision=tp / predicted if predicted else 0.,
            recall=tp / support if support else 0.,
            f1=2 * tp / (support + predicted) if support + predicted else 0.,
            support=support)
    curve = []
    thresholds = {r["score"] for r in accepted if r["score"] is not None}
    for threshold in sorted(thresholds, reverse=True):
        selected = [r for r in accepted
                    if r["score"] is not None and r["score"] >= threshold]
        correct = sum(r["expected"] == r["predicted"] for r in selected)
        curve.append(dict(threshold=threshold, accepted=len(selected),
                          coverage=len(selected) / n,
                          precision=correct / len(selected)))
    brier = ece = None
    calibration_reason = "score_not_calibrated"
    if score_type == "calibrated_probability":
        if not accepted:
            calibration_reason = "no_accepted_predictions"
        elif any(r["score"] is None for r in accepted):
            calibration_reason = "missing_scores"
        else:
            calibration_reason = None
        if calibration_reason is None:
            brier = sum(
                (r["score"] - (r["expected"] == r["predicted"])) ** 2
                for r in accepted) / len(accepted)
            bins = [[] for _ in range(10)]
            for row in accepted:
                bins[min(int(row["score"] * 10), 9)].append(row)
            ece = sum(
                abs(sum(r["score"] for r in bucket)
                    - sum(r["expected"] == r["predicted"] for r in bucket))
                for bucket in bins) / len(accepted)
    accepted_correct = sum(r["expected"] == r["predicted"] for r in accepted)
    metrics_reason = None
    if not n:
        metrics_reason = "empty_sample" if not rows else "no_known_expected"
    return dict(
        sample_count=len(rows), evaluated_count=n, unknown_expected_count=len(rows) - n,
        confusion_matrix=matrix, per_class=per_class,
        macro_f1=sum(v["f1"] for v in per_class.values()) / len(labels) if n else None,
        accuracy=sum(matrix[a][a] for a in labels) / n if n else None,
        majority_class=max(labels, key=lambda a: distribution[a]) if n else None,
        distribution=distribution, metrics_reason=metrics_reason,
        abstention=dict(count=n - len(accepted), coverage=len(accepted) / n if n else None,
                        precision=accepted_correct / len(accepted) if accepted else None,
                        reason=None if accepted else "no_accepted_predictions", curve=curve),
        brier=brier, ece=ece, calibration_reason=calibration_reason)
