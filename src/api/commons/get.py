from utils.logger_config import log
import json
from rich.console import Console
import sys

# Ensure console can handle UTF-8 characters
sys.stdout.reconfigure(encoding='utf-8')

console = Console()
def refresh_accounts_n_regions_table():
    from db.crud import DatabaseManager

    db_manager = DatabaseManager()
    db_manager.populate_accounts_and_regions()

def get_accounts_and_regions(account_ids: list = None) -> dict:
    from db.crud import DatabaseManager

    db_manager = DatabaseManager()
    accounts_and_regions_dict = db_manager.get_accounts_and_regions(account_ids=account_ids)
    return accounts_and_regions_dict

def get_recommendations(account_id: str = None, region: str = None, recommendation_type: str = None) -> dict:
    from db.crud import DatabaseManager

    db_manager = DatabaseManager()
    recommendations = db_manager.get_recommendations(account_id=account_id, region=region, recommendation_type=recommendation_type)

    accounts_and_regions = get_accounts_and_regions()

    log.debug(f"Grouped recommendations json for account_id: {account_id}, region: {region}, recommendation_type: {recommendation_type}")
    # Group recommendations by account, region, and recommendation type
    grouped_recommendations = {}
    for recommendation in recommendations:
        account = recommendation.account_id
        region = recommendation.region_name
        rec_type = recommendation.recommendation_type
        attributes = recommendation.attributes  # Attributes is already a dictionary
        account_name = accounts_and_regions.get(account, {}).get('account_name', 'Unknown')

        grouped_recommendations.setdefault((account, account_name), {}).setdefault(region, {}).setdefault(rec_type, []).append(attributes)
    return grouped_recommendations

def get_updatables(grouped_recommendations: dict) -> dict:
    updatables = {}
    for (account, account_name), regions in grouped_recommendations.items():
        for region, rec_types in regions.items():
            for rec_type, recs in rec_types.items():
                for rec in recs:
                    if "BluearchAction" in rec:
                        updatables.setdefault(account, {}).setdefault(region, {}).setdefault(rec_type, []).append(rec)
    log.debug(f"Updatables json: {json.dumps(updatables, indent=2)}")
    return updatables

def get_recommendation_types() -> list:
    from db.crud import DatabaseManager

    db_manager = DatabaseManager()
    recommendation_types = db_manager.get_recommendation_types()
    return recommendation_types