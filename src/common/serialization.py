"""
Serialization utilities for handling datetime and other non-JSON serializable objects.
"""

import json
from datetime import datetime
from typing import Any, Dict
from dataclasses import asdict, is_dataclass
from enum import Enum


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects and enums"""
    
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat() + 'Z'
        elif isinstance(obj, Enum):
            return obj.value
        return super().default(obj)


def serialize_dataclass(obj: Any) -> Dict[str, Any]:
    """
    Serialize a dataclass to a dictionary with proper datetime handling.
    
    Args:
        obj: The dataclass object to serialize
        
    Returns:
        Dictionary representation with datetime objects converted to ISO strings
    """
    if not is_dataclass(obj):
        raise ValueError("Object must be a dataclass")
    
    # Convert to dict
    data = asdict(obj)
    
    # Recursively convert datetime objects
    return _convert_datetimes(data)


def _convert_datetimes(obj: Any) -> Any:
    """
    Recursively convert datetime objects to timestamps and enums to values for dataclasses_json compatibility.
    
    Args:
        obj: Object to convert (can be dict, list, or primitive)
        
    Returns:
        Object with datetime objects converted to timestamps (integers) and enums to values
    """
    if isinstance(obj, datetime):
        return int(obj.timestamp())
    elif isinstance(obj, Enum):
        return obj.value
    elif isinstance(obj, dict):
        return {key: _convert_datetimes(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_convert_datetimes(item) for item in obj]
    else:
        return obj


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """
    Safely serialize an object to JSON with datetime handling.
    
    Args:
        obj: Object to serialize
        **kwargs: Additional arguments for json.dumps
        
    Returns:
        JSON string representation
    """
    return json.dumps(obj, cls=DateTimeEncoder, **kwargs)


def create_serializable_response(data: Any) -> Dict[str, Any]:
    """
    Create a serializable response from any data object.
    
    Args:
        data: Data to make serializable (dataclass, dict, list, etc.)
        
    Returns:
        Dictionary that can be safely serialized to JSON
    """
    if is_dataclass(data):
        # Use the dataclass's built-in to_dict method for proper serialization
        # This ensures compatibility with from_dict deserialization
        result = data.to_dict()
        # Convert any datetime objects to timestamps for JSON serialization
        return _convert_datetimes(result)
    elif isinstance(data, dict):
        # Convert datetime objects to timestamps for JSON serialization and dataclasses_json compatibility
        return _convert_datetimes(data)
    elif isinstance(data, list):
        return _convert_datetimes(data)
    else:
        return data