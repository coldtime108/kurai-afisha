"""Public deterministic planning endpoint, shared with the bot and assistant."""

from fastapi import Depends, HTTPException, Request
from .planner import DayPlanInput, DayPlanOut, build_day_plan


def install_planner(app, db, limit):
    @app.post("/api/v1/planner/day", response_model=DayPlanOut)
    def day_plan(data: DayPlanInput, request: Request, session=Depends(db)):
        limit(request, "planner", 60)
        try:
            return build_day_plan(session, data)
        except ValueError as error:
            raise HTTPException(422, str(error))
