"""Write the JSON Schema for every pydantic model in contracts/models.py to stdout."""
import inspect
import json

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from shiftwright_contracts import models

classes = [
    obj for _, obj in inspect.getmembers(models, inspect.isclass)
    if issubclass(obj, BaseModel) and obj is not BaseModel and obj.__module__ == models.__name__
]
_, schema = models_json_schema([(c, "validation") for c in classes], title="ShiftwrightContracts")
print(json.dumps(schema, indent=2))
