"""
SQL Schema Import endpoint for aaptor-rag-service.

Allows importing SQL schemas to MongoDB from external services.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core.settings import get_settings
from db.mongo import _get_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schema"])


class SchemaImportRequest(BaseModel):
    schemas: List[Dict[str, Any]]


class SchemaImportResponse(BaseModel):
    success: bool
    imported: int
    updated: int
    total: int
    message: str
    errors: list = []


@router.post("/api/v1/import-sql-schemas", response_model=SchemaImportResponse)
async def import_sql_schemas(
    request: SchemaImportRequest,
    x_admin_api_key: str | None = Header(None, alias="X-Admin-Api-Key"),
):
    """
    Import SQL schemas to MongoDB.
    
    This endpoint allows external services to import SQL schemas
    into the RAG service's MongoDB instance.
    
    Requires admin API key for authentication.
    """
    # Verify admin API key
    settings = get_settings()
    if settings.admin_api_key and x_admin_api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing admin API key")
    
    if not request.schemas:
        raise HTTPException(status_code=400, detail="No schemas provided")
    
    try:
        # Get MongoDB client
        client = _get_client()
        db = client[settings.mongodb_db_name]
        collection = db["sql_schemas"]
        
        # Create indexes ONCE before importing - use separate indexes for array fields
        # MongoDB cannot create compound indexes on multiple array fields (parallel arrays error)
        try:
            # Drop any existing bad compound index that may have been created
            try:
                collection.drop_index("domain_1_difficulty_levels_1_sql_categories_1")
            except Exception:
                pass  # Index may not exist, that's fine
            
            # Create separate single-field indexes (safe for array fields)
            collection.create_index("schema_id", unique=True)
            collection.create_index("domain")
            collection.create_index("difficulty_levels")
            collection.create_index("sql_categories")
            collection.create_index([("usage_count", 1), ("last_used_at", 1)])
        except Exception as idx_err:
            logger.warning(f"Index creation warning (non-fatal): {idx_err}")
        
        imported = 0
        updated = 0
        errors = []
        
        for schema in request.schemas:
            try:
                # Ensure required fields
                if "schema_id" not in schema:
                    errors.append(f"Schema missing schema_id: {schema.get('name', 'unknown')}")
                    continue
                
                # Add timestamps if not present
                if "created_at" not in schema:
                    schema["created_at"] = datetime.utcnow()
                schema["updated_at"] = datetime.utcnow()
                
                # Upsert schema
                result = collection.update_one(
                    {"schema_id": schema["schema_id"]},
                    {"$set": schema},
                    upsert=True
                )
                
                if result.upserted_id:
                    imported += 1
                elif result.modified_count > 0:
                    updated += 1
                else:
                    # Document exists but no changes
                    updated += 1
                    
            except Exception as e:
                errors.append(f"Error importing schema {schema.get('schema_id', 'unknown')}: {str(e)}")
                logger.error(f"Schema import error: {e}")
        
        total = len(request.schemas)
        success = (imported + updated) > 0
        
        message = f"Imported {imported} new schemas, updated {updated} existing schemas"
        if errors:
            message += f". {len(errors)} errors occurred"
            logger.warning(f"Schema import errors: {errors}")
        
        logger.info(f"Schema import completed: {imported} imported, {updated} updated, {len(errors)} errors")
        
        return SchemaImportResponse(
            success=success,
            imported=imported,
            updated=updated,
            total=total,
            message=message,
            errors=errors[:5]  # Return first 5 errors for debugging
        )
        
    except Exception as e:
        logger.error(f"Schema import failed: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.get("/api/v1/sql-schemas/select")
async def select_sql_schema(
    difficulty: str = "medium",
    sql_category: str = "select",
    domain: str | None = None,
    limit: int = 10
):
    """
    Select a random SQL schema matching the given criteria.
    Used by backend schema_generator to get schemas for question generation.
    """
    try:
        settings = get_settings()
        client = _get_client()
        db = client[settings.mongodb_db_name]
        collection = db["sql_schemas"]

        # Build query
        query = {
            "difficulty_levels": difficulty.lower(),
            "sql_categories": sql_category.lower()
        }
        if domain:
            query["domain"] = domain

        # Get least recently used schemas
        schemas = list(
            collection.find(query)
            .sort("usage_count", 1)
            .limit(limit)
        )

        if not schemas:
            # Fallback: try without difficulty filter
            query_fallback = {"sql_categories": sql_category.lower()}
            if domain:
                query_fallback["domain"] = domain
            schemas = list(
                collection.find(query_fallback)
                .sort("usage_count", 1)
                .limit(limit)
            )

        if not schemas:
            raise HTTPException(
                status_code=404,
                detail=f"No schema found for difficulty='{difficulty}', category='{sql_category}', domain='{domain}'"
            )

        # Pick random from top results
        import random
        selected = random.choice(schemas)

        # Convert ObjectId to string
        selected["_id"] = str(selected["_id"])

        return selected

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to select schema: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to select schema: {str(e)}")


@router.post("/api/v1/sql-schemas/update-usage/{schema_id}")
async def update_schema_usage(schema_id: str):
    """
    Increment usage count for a schema after it's been used for question generation.
    """
    try:
        settings = get_settings()
        client = _get_client()
        db = client[settings.mongodb_db_name]
        collection = db["sql_schemas"]

        collection.update_one(
            {"schema_id": schema_id},
            {
                "$inc": {"usage_count": 1},
                "$set": {"last_used_at": datetime.utcnow()}
            }
        )

        return {"success": True, "schema_id": schema_id}

    except Exception as e:
        logger.error(f"Failed to update schema usage: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update usage: {str(e)}")
async def get_schema_count():
    """
    Get count of SQL schemas in MongoDB.
    """
    try:
        settings = get_settings()
        client = _get_client()
        db = client[settings.mongodb_db_name]
        collection = db["sql_schemas"]
        
        count = collection.count_documents({})
        
        return {
            "count": count,
            "collection": "sql_schemas",
            "database": settings.mongodb_db_name
        }
        
    except Exception as e:
        logger.error(f"Failed to get schema count: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get count: {str(e)}")


@router.get("/api/v1/sql-schemas/stats")
async def get_schema_stats():
    """
    Get statistics about SQL schemas in MongoDB.
    """
    try:
        settings = get_settings()
        client = _get_client()
        db = client[settings.mongodb_db_name]
        collection = db["sql_schemas"]
        
        # Count by domain
        domain_pipeline = [
            {"$group": {"_id": "$domain", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        domain_stats = list(collection.aggregate(domain_pipeline))
        
        # Count by difficulty
        difficulty_pipeline = [
            {"$unwind": "$difficulty_levels"},
            {"$group": {"_id": "$difficulty_levels", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        difficulty_stats = list(collection.aggregate(difficulty_pipeline))
        
        # Count by SQL category
        category_pipeline = [
            {"$unwind": "$sql_categories"},
            {"$group": {"_id": "$sql_categories", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        category_stats = list(collection.aggregate(category_pipeline))
        
        total_count = collection.count_documents({})
        
        return {
            "total_schemas": total_count,
            "by_domain": domain_stats,
            "by_difficulty": difficulty_stats,
            "by_category": category_stats
        }
        
    except Exception as e:
        logger.error(f"Failed to get schema stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
