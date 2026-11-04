from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from app.roles import Role
from app.loyalty import MAX_POINTS


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(StrictModel):
    email: str = Field(min_length=3, max_length=180)
    password: str = Field(min_length=1, max_length=128)


class AccountCredentials(StrictModel):
    email: str = Field(min_length=3, max_length=180, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator('email', mode='before')
    @classmethod
    def normalize_email(cls, value):
        if isinstance(value, str):
            value = value.strip().lower()
        return value

    @field_validator('password')
    @classmethod
    def nonblank_password(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError('Password must not be blank.')
        return value


class SignupInput(AccountCredentials):
    name: str = Field(min_length=1, max_length=120)
    birthday: date | None = None
    confirm_password: SecretStr | None = Field(default=None, min_length=12, max_length=128)

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('birthday', mode='before')
    @classmethod
    def plain_birthday(cls, value):
        if value is not None and type(value) is not date and (
                not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value)):
            raise ValueError('Birthday must be a date in YYYY-MM-DD format.')
        return value

    @field_validator('birthday')
    @classmethod
    def valid_birthday(cls, value):
        if value is not None:
            if value.year < 1000:
                raise ValueError('Birthday must be on or after 1000-01-01.')
            if value > datetime.now(timezone(timedelta(hours=8))).date():
                raise ValueError('Birthday cannot be in the future.')
        return value

    @model_validator(mode='after')
    def matching_passwords(self):
        if self.confirm_password is not None and self.password.get_secret_value() != self.confirm_password.get_secret_value():
            raise ValueError('Passwords do not match.')
        return self


class InitialAdminInput(AccountCredentials):
    pass


class PrivilegedAccountInput(AccountCredentials):
    role: Literal['admin', 'staff']


class AccountCreateInput(AccountCredentials):
    role: Role
    name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode='after')
    def customer_name_only(self):
        if self.role == Role.CUSTOMER and self.name is None:
            raise ValueError('Customer accounts require a name.')
        if self.role != Role.CUSTOMER and self.name is not None:
            raise ValueError('Only linked customer records have a customer name.')
        return self


class AccountDetailsInput(StrictModel):
    email: str = Field(min_length=3, max_length=180, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator('email', mode='before')
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator('name', mode='before')
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class AccountPasswordInput(StrictModel):
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator('password')
    @classmethod
    def nonblank_password(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError('Password must not be blank.')
        return value


class AccountResult(StrictModel):
    id: int = Field(gt=0)
    email: str
    role: Role
    customer_id: int | None
    active: bool


class AccountListResult(AccountResult):
    name: str | None


class SignupResult(StrictModel):
    id: int = Field(gt=0)
    email: str
    role: Literal['customer']
    customer_id: int = Field(gt=0)


class AccountRoleInput(StrictModel):
    role: Role


class AccountStatusInput(StrictModel):
    active: bool = Field(strict=True)


class MenuInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    active: bool = True


class CustomerInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=180)


class CartLine(StrictModel):
    menu_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100, strict=True)


class CheckoutInput(StrictModel):
    request_key: str = Field(min_length=8, max_length=80)
    branch_id: int = Field(gt=0)
    customer_id: int = Field(gt=0)
    redeem_points: int = Field(default=0, ge=0, le=1_000_000, strict=True)
    lines: list[CartLine] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def unique_items(self):
        ids = [line.menu_item_id for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError('Combine repeated menu items into one cart line.')
        return self


def plain_stock_decimal(value):
    if isinstance(value, str) and not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,3})?', value):
        raise ValueError('Use digits and up to three decimal places for ingredient quantities.')
    return value


class RestockInput(StrictModel):
    branch_id: int = Field(gt=0, strict=True)
    ingredient_id: int = Field(gt=0, strict=True)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    note: str = Field(default='', max_length=255)

    @field_validator('quantity', mode='before')
    @classmethod
    def plain_quantity(cls, value):
        return plain_stock_decimal(value)


class RecipeIngredientInput(StrictModel):
    ingredient_id: int = Field(gt=0, strict=True)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)

    @field_validator('quantity', mode='before')
    @classmethod
    def plain_quantity(cls, value):
        return plain_stock_decimal(value)


class RecipeInput(StrictModel):
    components: list[RecipeIngredientInput] = Field(min_length=1, max_length=100)
    expected_components: list[RecipeIngredientInput] = Field(max_length=100)

    @model_validator(mode='after')
    def unique_ingredients(self):
        for components in (self.components, self.expected_components):
            ids = [component.ingredient_id for component in components]
            if len(ids) != len(set(ids)):
                raise ValueError('Each ingredient can appear only once in a recipe.')
        return self


class StockAdjustmentInput(StrictModel):
    quantity: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    expected_quantity: Decimal = Field(ge=0, max_digits=14, decimal_places=3)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator('quantity', 'expected_quantity', mode='before')
    @classmethod
    def plain_quantity(cls, value):
        return plain_stock_decimal(value)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class PointsCorrectionInput(StrictModel):
    expected_points: int = Field(ge=0, le=MAX_POINTS, strict=True)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class PointsEditInput(PointsCorrectionInput):
    points: int = Field(ge=0, le=MAX_POINTS, strict=True)


class PointsRemovalInput(PointsCorrectionInput):
    amount: int = Field(gt=0, le=MAX_POINTS, strict=True)


class ReviewInput(StrictModel):
    order_id: int = Field(gt=0)
    rating: int = Field(ge=1, le=5, strict=True)
    text: str = Field(min_length=3, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    category_ratings: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_nested(self):
        if len(self.tags) != len(set(self.tags)) or any(not t.strip() or len(t) > 40 for t in self.tags):
            raise ValueError('Tags must be unique, nonempty and at most 40 characters.')
        if any(k not in {'food', 'service', 'value'} or type(v) is not int or not 1 <= v <= 5
               for k, v in self.category_ratings.items()):
            raise ValueError('Category ratings support food/service/value, each an integer 1-5.')
        return self


class ReplyInput(StrictModel):
    text: str = Field(min_length=1, max_length=1000)


class ProfileInput(StrictModel):
    dietary_preferences: list[str] = Field(default_factory=list, max_length=10)
    favourite_tags: list[str] = Field(default_factory=list, max_length=10)
    @model_validator(mode='after')
    def bounded_preferences(self):
        if any(not x.strip() or len(x) > 40 for x in self.dietary_preferences + self.favourite_tags):
            raise ValueError('Preference labels must be 1-40 characters.')
        return self
