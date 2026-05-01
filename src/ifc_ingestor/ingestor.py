import ifcopenshell
from pathlib import Path
from app.contracts import IfcBundle
#from typing import Optional
#from __future__ import annotations

def load_ifc_bundle(ifc_path: str) -> IfcBundle:
    """
    Load an IFC file and wrap it into an IfcBundle together with minimal metadata.
    
    Parameters
    ----------
    ifc_path : str
        Input IFC file path.

    Returns
    -------
    IfcBundle
        - schema: IFC schema name (e.g., "IFC2X3")
        - source_path: Input IFC file path (converted to absolute path)
        - model: ifcopenshell.file object

    Raises
    ------
    FileNotFoundError
        File not found.
    RuntimeError
        Failed to open the file.
    """
    path_obj = Path(ifc_path)

    if not path_obj.is_file():
        raise FileNotFoundError(f"IFC file not found: {path_obj}")

    try:
        model = ifcopenshell.open(str(path_obj))
    except Exception as exc:  # type: ignore[broad-except]
        raise RuntimeError(f"Failed to open IFC file with ifcopenshell: {path_obj}") from exc

    schema = _detect_schema(model)
    # Converting the path to an absolute path simplifies handling in downstream modules.
    abs_path = str(path_obj.resolve())

    return IfcBundle(
        schema=schema,
        source_path=abs_path,
        model=model,
    )


def _detect_schema(model: "ifcopenshell.file") -> str:
    """
    Helper function for retrieving the IFC schema name from an ifcopenshell model.
    Typical return values include "IFC2X3" , "IFC4" , "IFC4X3" , and related schema identifiers.
    """
    # Attribute names may vary depending on the ifcopenshell version,
    # so getattr is used as a defensive approach.
    for attr in ("schema", "schema_name", "schema_identifier"):
        schema = getattr(model, attr, None)
        if isinstance(schema, str) and schema:
            return schema.upper()

    # Fallback if retrieval fails
    return "UNKNOWN"
