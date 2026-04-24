from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.connection import Connection
from app.models.object import ModelObject
from app.schemas.connection import ConnectionResponse
from app.schemas.object import ObjectResponse
from app.services import mermaid_service, structurizr_service

router = APIRouter(tags=["import-export"])


@router.get("/export")
async def export_model(db: AsyncSession = Depends(get_db)):
    objects_result = await db.execute(select(ModelObject).order_by(ModelObject.name))
    connections_result = await db.execute(select(Connection))

    objects = [
        ObjectResponse.from_model(obj).model_dump(mode="json")
        for obj in objects_result.scalars().all()
    ]
    connections = [
        ConnectionResponse.model_validate(c).model_dump(mode="json")
        for c in connections_result.scalars().all()
    ]

    return JSONResponse({
        "version": "1.0",
        "objects": objects,
        "connections": connections,
    })


@router.post("/import", status_code=201)
async def import_model(file: UploadFile, db: AsyncSession = Depends(get_db)):
    import json

    try:
        content = await file.read()
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail="Invalid JSON file") from e

    if "objects" not in data:
        raise HTTPException(status_code=400, detail="Missing 'objects' field")

    id_map: dict[str, str] = {}  # old_id -> new_id
    created_objects = 0
    created_connections = 0

    # First pass: create objects without parent_id
    for obj_data in data.get("objects", []):
        old_id = obj_data.get("id")
        obj = ModelObject(
            name=obj_data["name"],
            type=obj_data["type"],
            scope=obj_data.get("scope", "internal"),
            status=obj_data.get("status", "live"),
            description=obj_data.get("description"),
            icon=obj_data.get("icon"),
            technology_ids=obj_data.get("technology_ids"),
            tags=obj_data.get("tags"),
            owner_team=obj_data.get("owner_team"),
            external_links=obj_data.get("external_links"),
            metadata_=obj_data.get("metadata"),
        )
        db.add(obj)
        await db.flush()
        if old_id:
            id_map[old_id] = str(obj.id)
        created_objects += 1

    # Second pass: set parent_id
    for obj_data in data.get("objects", []):
        old_id = obj_data.get("id")
        old_parent_id = obj_data.get("parent_id")
        if old_id and old_parent_id and old_parent_id in id_map:
            new_id = id_map[old_id]
            result = await db.execute(select(ModelObject).where(ModelObject.id == new_id))
            obj = result.scalar_one()
            obj.parent_id = id_map[old_parent_id]

    # Create connections
    for conn_data in data.get("connections", []):
        old_source = conn_data.get("source_id")
        old_target = conn_data.get("target_id")
        if old_source in id_map and old_target in id_map:
            conn = Connection(
                source_id=id_map[old_source],
                target_id=id_map[old_target],
                label=conn_data.get("label"),
                protocol_ids=conn_data.get("protocol_ids"),
                direction=conn_data.get("direction", "unidirectional"),
                tags=conn_data.get("tags"),
            )
            db.add(conn)
            created_connections += 1

    await db.flush()

    return {
        "created_objects": created_objects,
        "created_connections": created_connections,
    }


@router.post("/import/structurizr", status_code=201)
async def import_structurizr(
    dsl: str = Body(..., media_type="text/plain"),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-import a Structurizr DSL blob. Body is the raw DSL text."""
    try:
        return await structurizr_service.import_dsl(db, dsl)
    except structurizr_service.StructurizrParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/import/mermaid", status_code=201)
async def import_mermaid(
    src: str = Body(..., media_type="text/plain"),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-import a Mermaid flowchart or C4 diagram. Body is the raw source."""
    try:
        return await mermaid_service.import_mermaid(db, src)
    except mermaid_service.MermaidParseError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
