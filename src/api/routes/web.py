from typing import Optional
from commons import get, execution
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

webapp = FastAPI()
templates = Jinja2Templates(directory="templates")

@webapp.get("/refresh")
def refresh_web():
    message = get.refresh_accounts_n_regions_table()
    return {"message": message}

@webapp.get("/accounts_and_regions/{account_ids}")
def get_accounts_and_regions_web(account_ids: str):
    account_id_list = [account_id.strip() for account_id in account_ids.split(",")]
    accounts_and_regions = get.get_accounts_and_regions(account_id_list)
    return accounts_and_regions

@webapp.get("/accounts_and_regions")
def get_accounts_and_regions_web2():
    accounts_and_regions = get.get_accounts_and_regions()
    return accounts_and_regions

@webapp.get("/recommendations")
def get_recommendations_web(
    account_id: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    recommendation_type: Optional[str] = Query(None)
):    
    serialized_recommendations = get.get_recommendations(account_id, region, recommendation_type)
    return serialized_recommendations

@webapp.get("/recommendation_types")
def get_recommendation_types_web():
    recommendation_types = get.get_recommendation_types()
    return {"recommendation_types": recommendation_types}

@webapp.get("/recommendations_html", response_class=HTMLResponse)
async def recommendations_html(request: Request, account_id: Optional[str] = None, region: Optional[str] = None, recommendation_type: Optional[str] = None):
    recommendations = get_recommendations_web(account_id=account_id, region=region, recommendation_type=recommendation_type)
    return templates.TemplateResponse("recommendations_report.html", {"request": request, "recommendations": recommendations})

@webapp.post("/populate")
def populate_web():
    return execution.populate()