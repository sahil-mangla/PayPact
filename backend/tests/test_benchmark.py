import pytest
from app.lab.benchmark import IntegrityLab


@pytest.fixture
def lab():
    return IntegrityLab()


@pytest.mark.asyncio
async def test_scenario_a_happy_path(lab):
    res = await lab.run_scenario("SC-A", "PROPOSED_APIL")
    assert res.protection_successful is True
    assert res.allowed_payment is True
    assert res.final_state == "PAID"


@pytest.mark.asyncio
async def test_scenario_b_price_drift_contrast(lab):
    # Baseline A & B fail (unauthorized payment allowed)
    res_a = await lab.run_scenario("SC-B", "BASELINE_A")
    assert res_a.protection_successful is False
    assert res_a.allowed_payment is True

    res_b = await lab.run_scenario("SC-B", "BASELINE_B")
    assert res_b.protection_successful is False
    assert res_b.allowed_payment is True

    # Proposed APIL succeeds (payment blocked, drift detected)
    res_apil = await lab.run_scenario("SC-B", "PROPOSED_APIL")
    assert res_apil.protection_successful is True
    assert res_apil.allowed_payment is False
    assert res_apil.drift_detected is True


@pytest.mark.asyncio
async def test_scenario_c_revoked_policy(lab):
    res = await lab.run_scenario("SC-C", "PROPOSED_APIL")
    assert res.protection_successful is True
    assert res.allowed_payment is False


@pytest.mark.asyncio
async def test_scenario_d_product_substitution(lab):
    res = await lab.run_scenario("SC-D", "PROPOSED_APIL")
    assert res.protection_successful is True
    assert res.allowed_payment is False
    assert res.drift_detected is True


@pytest.mark.asyncio
async def test_scenario_e_duplicate_submission(lab):
    res = await lab.run_scenario("SC-E", "PROPOSED_APIL")
    assert res.protection_successful is True
    assert res.duplicate_blocked is True


@pytest.mark.asyncio
async def test_scenario_f_prompt_injection(lab):
    res = await lab.run_scenario("SC-F", "PROPOSED_APIL")
    assert res.protection_successful is True
    assert res.allowed_payment is False


@pytest.mark.asyncio
async def test_scenario_g_timeout_reconciliation(lab):
    res = await lab.run_scenario("SC-G", "PROPOSED_APIL")
    assert res.protection_successful is True


@pytest.mark.asyncio
async def test_full_benchmark_matrix(lab):
    report = await lab.run_full_benchmark()
    assert report.total_scenarios == 21  # 7 scenarios * 3 systems
    
    summary = report.summary_by_system
    # Proposed APIL must have 100% pass rate
    assert summary["PROPOSED_APIL"]["pass_rate_pct"] == 100.0
    assert summary["PROPOSED_APIL"]["unauthorized_spend_count"] == 0

    # Baseline A must have significant failures / unauthorized spend
    assert summary["BASELINE_A"]["pass_rate_pct"] < 50.0
    assert summary["BASELINE_A"]["unauthorized_spend_count"] >= 4

    # Baseline B must also have failures due to missing lifecycle checks
    assert summary["BASELINE_B"]["pass_rate_pct"] < 60.0
    assert summary["BASELINE_B"]["unauthorized_spend_count"] >= 3
