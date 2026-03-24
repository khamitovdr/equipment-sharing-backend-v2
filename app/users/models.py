from tortoise import fields
from tortoise.models import Model

from app.core.enums import UserRole


class User(Model):
    id = fields.UUIDField(pk=True)
    email = fields.CharField(max_length=255, unique=True)
    hashed_password = fields.CharField(max_length=255)
    phone = fields.CharField(max_length=20)
    name = fields.CharField(max_length=150)
    middle_name = fields.CharField(max_length=150, null=True)
    surname = fields.CharField(max_length=150)
    role = fields.CharEnumField(UserRole, default=UserRole.USER, max_length=20)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "users"
