from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(StrictModel):
    email: str = Field(min_length=3, max_length=180)
    password: str = Field(min_length=1, max_length=128)


class MenuInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    active: bool = True

    @field_validator('name')
    @classmethod
    def nonblank_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Dish name must not be blank.')
        return value


class IngredientInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(default='g', min_length=1, max_length=12)

    @field_validator('name', 'unit')
    @classmethod
    def nonblank_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Ingredient name and unit must not be blank.')
        return value


class RecipeIngredientInput(StrictModel):
    ingredient_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class RecipeInput(StrictModel):
    ingredients: list[RecipeIngredientInput] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_ingredients(self):
        ids = [line.ingredient_id for line in self.ingredients]
        if len(ids) != len(set(ids)):
            raise ValueError('An ingredient may only appear once in a recipe.')
        return self


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


class RestockInput(StrictModel):
    branch_id: int = Field(gt=0)
    ingredient_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    note: str = Field(default='', max_length=255)


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
