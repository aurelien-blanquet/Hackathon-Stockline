"""market/levers.py: the buyer learns which argument moves each producer, and uses it."""

from app.market.express import negotiate
from app.market.levers import LEVERS, LeverMemory, Stat, available, buyer_line, sensitivity
from app.market.strategy import NeedLine, SupplierProfile


def test_the_supplier_sheet_hints_at_a_lever_and_fixed_price_moves_on_nothing():
    plain = sensitivity("sup_x", "", False)
    volume = sensitivity("sup_x", "Négocie surtout sur les volumes : à la palette, il fait un geste.", False)
    assert volume["volume"] > plain["volume"] and volume["paiement"] == plain["paiement"]
    assert set(sensitivity("sup_x", "Prix fixe, aucune remise.", True).values()) == {0.0}


def test_each_lever_is_tried_once_then_the_best_one_is_used():
    m = LeverMemory()
    options = available(urgent=False, has_rival=True)
    tried = []
    for _ in range(len(options)):
        lever = m.choose("sup_a", options)
        tried.append(lever)
        m.record("sup_a", lever, 0.04 if lever == "paiement" else 0.01)
    assert sorted(tried) == sorted(options)
    assert m.choose("sup_a", options) == "paiement" and m.best("sup_a") == "paiement"


def test_no_promise_the_buyer_cannot_keep():
    assert "souplesse" not in available(urgent=True, has_rival=True)  # the customer is waiting: no « your next truck »
    assert "concurrence" not in available(urgent=False, has_rival=False)  # no rival price, no rival argument


def test_the_rival_is_never_named():
    line = buyer_line("concurrence", "la tomme", "12,37 €", first=True)
    assert "12,37 €" in line and "ailleurs" in line
    assert all(buyer_line(lv, "la tomme", "12,37 €", first=True) for lv in LEVERS)


def test_memory_survives_a_restart(tmp_path):
    path = tmp_path / "memory.json"
    m = LeverMemory(path=path)
    m.stats = {"sup_a": {"volume": Stat(3, 0.025)}}
    m.rounds = 3
    m.save()
    again = LeverMemory.load(path)
    assert again.rounds == 3 and again.best("sup_a") == "volume" and again.stats["sup_a"]["volume"].n == 3


def _market():
    line = NeedLine("prd_t", "Tomme de Savoie IGP", "kg", "fromage", 12.0, 40.0, {"sup_a": 13.0, "sup_b": 13.2})
    profiles = {"sup_a": SupplierProfile("sup_a", "Coop", flexibility=2, persona="Négocie sur les volumes, à la palette."),
                "sup_b": SupplierProfile("sup_b", "Fruitière", flexibility=3, persona="Tient à la fidélité de ses clients.")}
    return [line], profiles


def test_learning_beats_the_competitor_price_alone_over_a_few_rounds():
    lines, profiles = _market()
    memory, base, learned = LeverMemory(), [], []
    for day in range(8):
        base.append(negotiate(lines, profiles, f"d{day}").decision.total)
        script = negotiate(lines, profiles, f"d{day}", memory=memory)
        memory.learn(script)
        learned.append(script.decision.total)
    assert sum(learned[-4:]) < sum(base[-4:])  # cheaper once learned
    assert memory.rounds == 8 and {memory.best("sup_a"), memory.best("sup_b")} <= set(LEVERS)
    steps = [st for sts in script.steps.values() for st in sts if st.kind == "counter"]
    assert all(st.lever for st in steps) and all(len({st.lever for st in sts if st.kind == "counter"}) == len([st for st in sts if st.kind == "counter"]) for sts in script.steps.values())  # fmt: skip
