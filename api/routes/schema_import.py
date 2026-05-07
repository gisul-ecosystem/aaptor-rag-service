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


@router.delete("/api/v1/sql-schemas/bulk-delete")
async def bulk_delete_schemas(
    x_admin_api_key: str | None = Header(None, alias="X-Admin-Api-Key"),
    source_quality: str | None = None,
    source: str | None = None,
    min_columns: int | None = None,
    max_columns: int | None = None,
    drop_all: bool = False
):
    """
    Bulk delete SQL schemas from MongoDB based on filters.
    
    Requires admin API key for authentication.
    
    Query params:
    - source_quality: Delete schemas with this source_quality (e.g., "spider_benchmark")
    - source: Delete schemas from this source (e.g., "sql_dataset_clean_v2.json")
    - min_columns: Delete schemas with fewer than this many columns
    - max_columns: Delete schemas with more than this many columns
    - drop_all: If true, drops the entire collection (use with caution!)
    
    Examples:
    - Delete all junk schemas with < 10 columns: ?min_columns=10
    - Delete all from bad source: ?source=sql_dataset_clean_v2.json
    - Drop entire collection: ?drop_all=true
    """
    settings = get_settings()
    if settings.admin_api_key and x_admin_api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing admin API key")
    
    try:
        client = _get_client()
        db = client[settings.mongodb_db_name]
        collection = db["sql_schemas"]
        
        if drop_all:
            # Drop entire collection
            count_before = collection.count_documents({})
            collection.drop()
            logger.warning(f"Dropped entire sql_schemas collection ({count_before} schemas)")
            return {
                "success": True,
                "deleted": count_before,
                "message": f"Dropped entire collection ({count_before} schemas)"
            }
        
        # Build delete query
        query = {}
        
        if source_quality:
            query["source_quality"] = {"$ne": source_quality}  # Delete everything NOT matching
        
        if source:
            query["source"] = source
        
        if min_columns is not None:
            query["metadata.total_columns"] = {"$lt": min_columns}
        
        if max_columns is not None:
            if "metadata.total_columns" in query:
                query["metadata.total_columns"]["$gt"] = max_columns
            else:
                query["metadata.total_columns"] = {"$gt": max_columns}
        
        if not query:
            raise HTTPException(
                status_code=400,
                detail="No filter provided. Use source_quality, source, min_columns, max_columns, or drop_all=true"
            )
        
        # Count before delete
        count_to_delete = collection.count_documents(query)
        
        if count_to_delete == 0:
            return {
                "success": True,
                "deleted": 0,
                "message": "No schemas matched the filter"
            }
        
        # Delete
        result = collection.delete_many(query)
        
        logger.info(f"Bulk deleted {result.deleted_count} schemas with query: {query}")
        
        return {
            "success": True,
            "deleted": result.deleted_count,
            "message": f"Deleted {result.deleted_count} schemas",
            "query": str(query)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk delete failed: {e}")
        raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")


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


@router.get("/api/v1/sql-schemas/list")
async def list_sql_schemas(
    limit: int = 200,
    skip: int = 0,
    domain: str | None = None,
    fields: str = "schema_id,domain,sample_data_row_counts",
):
    """
    List all SQL schemas with optional filtering.
    Returns schema_id, domain, and sample data row counts for verification.

    Query params:
    - limit: max schemas to return (default 200, max 500)
    - skip: pagination offset
    - domain: filter by domain
    - fields: comma-separated fields to return (default: schema_id,domain,sample_data_row_counts)
    """
    try:
        settings = get_settings()
        client = _get_client()
        db = client[settings.mongodb_db_name]
        collection = db["sql_schemas"]

        limit = min(limit, 500)

        # Build query
        query = {}
        if domain:
            query["domain"] = domain

        # Determine projection based on requested fields
        field_list = [f.strip() for f in fields.split(",")]
        projection = {"_id": 0, "schema_id": 1, "domain": 1}

        # Always include sample_data if row counts requested
        include_sample_data = "sample_data_row_counts" in field_list or "sample_data" in field_list
        if include_sample_data:
            projection["sample_data"] = 1

        # Include other requested fields
        for f in field_list:
            if f not in ("sample_data_row_counts", "schema_id", "domain"):
                projection[f] = 1

        schemas = list(
            collection.find(query, projection)
            .sort("schema_id", 1)
            .skip(skip)
            .limit(limit)
        )

        total = collection.count_documents(query)

        # Build response — compute row counts if requested
        results = []
        for s in schemas:
            entry = {
                "schema_id": s.get("schema_id"),
                "domain": s.get("domain"),
            }

            if include_sample_data:
                sample_data = s.get("sample_data", {})
                row_counts = {t: len(rows) for t, rows in sample_data.items()}
                total_rows = sum(row_counts.values())
                min_rows = min(row_counts.values()) if row_counts else 0
                entry["sample_data_row_counts"] = row_counts
                entry["total_rows"] = total_rows
                entry["min_rows_per_table"] = min_rows
                entry["tables_count"] = len(row_counts)

            # Include any other requested fields
            for f in field_list:
                if f not in ("sample_data_row_counts", "schema_id", "domain", "sample_data"):
                    if f in s:
                        entry[f] = s[f]

            results.append(entry)

        return {
            "total": total,
            "returned": len(results),
            "skip": skip,
            "limit": limit,
            "schemas": results,
        }

    except Exception as e:
        logger.error(f"Failed to list schemas: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list schemas: {str(e)}")
