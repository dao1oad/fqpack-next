# -*- coding: utf-8 -*-

from typing import Optional

from bson import ObjectId
from pydantic import BaseModel, Field


class MyBaseModel(BaseModel):
    id: Optional[ObjectId] = Field(alias='_id')

    class Config:
        arbitrary_types_allowed = True
