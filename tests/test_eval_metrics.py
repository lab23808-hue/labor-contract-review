from evaluation.metrics import extract_article, mean, recall_at_k, reciprocal_rank


def test_extract_article():
    assert extract_article("《劳动合同法》第二十条") == "第二十条"
    assert extract_article("没有条号") is None


def test_recall_at_k_hit_and_miss():
    gold = ["《劳动合同法》第二十条"]
    assert recall_at_k(gold, ["第二十条", "第十九条"], k=5) == 1.0
    assert recall_at_k(gold, ["第十九条"], k=5) == 0.0


def test_recall_at_k_empty_gold_is_none():
    assert recall_at_k([], ["第二十条"], k=5) is None


def test_recall_at_k_respects_k():
    gold = ["第二十条"]
    assert recall_at_k(gold, ["第十九条", "第二十条"], k=1) == 0.0
    assert recall_at_k(gold, ["第十九条", "第二十条"], k=2) == 1.0


def test_reciprocal_rank():
    gold = ["第二十条"]
    assert reciprocal_rank(gold, ["第十九条", "第二十条"], k=5) == 0.5
    assert reciprocal_rank(gold, ["第十九条"], k=5) == 0.0
    assert reciprocal_rank([], ["第二十条"], k=5) is None


def test_mean_ignores_none():
    assert mean([1.0, None, 0.0]) == 0.5
    assert mean([None]) is None
