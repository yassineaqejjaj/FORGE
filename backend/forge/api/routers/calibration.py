"""Router ``calibration``: agreement between AI judges and human evaluators (docs §9.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from forge.api.deps import RequireViewer, SessionDep
from forge.api.routers.benchmarks import analytics_errors
from forge.api.schemas.calibration import CalibrationOut
from forge.services import calibration as service

router = APIRouter(tags=["calibration"])


@router.get(
    "/calibration",
    response_model=CalibrationOut,
    summary="Calibration IA / humain par juge et par critère (accord, corrélations, kappa pondéré)",
)
async def get_calibration(
    session: SessionDep,
    principal: RequireViewer,
    judge_id: uuid.UUID | None = None,
    criterion_key: str | None = None,
    dataset_id: uuid.UUID | None = None,
) -> CalibrationOut:
    with analytics_errors():
        data = await service.calibration_report(
            session, principal, judge_id=judge_id, criterion_key=criterion_key, dataset_id=dataset_id
        )
    return CalibrationOut.model_validate(data)
