"""Highway Bites seed data — the mock fast-food chain for the POC.

All prices are in paise (1 INR = 100 paise). Indian highway QSR price points:
veg burger ~₹89-149, chicken burger ~₹149-249, combos ~₹229-399.

is_veg semantics (binary, strict-vegetarian interpretation):
  1 = pure vegetarian (no meat, fish, OR egg)
  0 = non-vegetarian (contains meat, fish, or egg)
Egg-containing baked goods and the egg burger are non-veg under this rule.
"""

from typing import TypedDict


class MenuItem(TypedDict):
    name: str
    category: str
    subcategory: str | None
    is_veg: bool
    price_paise: int
    description: str


class Combo(TypedDict):
    name: str
    is_veg: bool
    price_paise: int
    description: str
    item_names: list[str]


class Modification(TypedDict):
    name: str
    price_delta_paise: int
    applies_to_category: str | None
    description: str


class Promotion(TypedDict, total=False):
    name: str
    description: str
    discount_type: str
    discount_value: int
    min_subtotal_paise: int | None  # None or omitted = no threshold
    condition: dict | None          # required for combo_price_paise; serialized to condition_json on insert


MENU_ITEMS: list[MenuItem] = [
    # Burgers — veg
    {"name": "Aloo Tikki Burger",        "category": "burger", "subcategory": "veg",     "is_veg": True,  "price_paise":  8900, "description": "Spiced potato patty, lettuce, tomato, mint mayo"},
    {"name": "Paneer Makhani Burger",    "category": "burger", "subcategory": "veg",     "is_veg": True,  "price_paise": 14900, "description": "Grilled paneer in makhani sauce, onion, lettuce"},
    {"name": "Veggie Supreme Burger",    "category": "burger", "subcategory": "veg",     "is_veg": True,  "price_paise": 17900, "description": "Double veg patty, cheese, jalapenos, lettuce"},
    {"name": "Corn & Cheese Burger",     "category": "burger", "subcategory": "veg",     "is_veg": True,  "price_paise": 11900, "description": "Sweet corn patty, melted cheese, garlic mayo"},
    {"name": "Spicy Bean Burger",        "category": "burger", "subcategory": "veg",     "is_veg": True,  "price_paise":  9900, "description": "Rajma patty, smoky chipotle sauce, onion"},
    # Burgers — chicken
    {"name": "Crispy Chicken Burger",    "category": "burger", "subcategory": "chicken", "is_veg": False, "price_paise": 14900, "description": "Crispy fried chicken patty, lettuce, mayo"},
    {"name": "Grilled Chicken Burger",   "category": "burger", "subcategory": "chicken", "is_veg": False, "price_paise": 16900, "description": "Grilled chicken patty, herb mayo, tomato"},
    {"name": "Tandoori Chicken Burger",  "category": "burger", "subcategory": "chicken", "is_veg": False, "price_paise": 17900, "description": "Tandoori-marinated chicken, mint chutney, onion"},
    {"name": "Spicy Peri Peri Chicken Burger","category": "burger", "subcategory": "chicken", "is_veg": False, "price_paise": 18900, "description": "Peri-peri chicken, cheese, jalapenos"},
    {"name": "Double Chicken Burger",    "category": "burger", "subcategory": "chicken", "is_veg": False, "price_paise": 24900, "description": "Two crispy chicken patties, cheese, bacon mayo"},
    {"name": "Chicken Maharaja Burger",  "category": "burger", "subcategory": "chicken", "is_veg": False, "price_paise": 26900, "description": "Premium grilled chicken, cheddar, smoky sauce"},
    # Burgers — fish / egg
    {"name": "Fish Fillet Burger",       "category": "burger", "subcategory": "fish",    "is_veg": False, "price_paise": 16900, "description": "Crispy fish fillet, tartar sauce, lettuce"},
    {"name": "Egg & Cheese Burger",      "category": "burger", "subcategory": "egg",     "is_veg": False, "price_paise":  9900, "description": "Fried egg, cheese, mayo, onion"},

    # Sides
    {"name": "Regular Fries",            "category": "side", "subcategory": "fries",     "is_veg": True,  "price_paise":  7900, "description": "Crispy salted fries"},
    {"name": "Large Fries",              "category": "side", "subcategory": "fries",     "is_veg": True,  "price_paise": 11900, "description": "Crispy salted fries, large portion"},
    {"name": "Peri Peri Fries",          "category": "side", "subcategory": "fries",     "is_veg": True,  "price_paise":  9900, "description": "Fries tossed in peri-peri seasoning"},
    {"name": "Masala Wedges",            "category": "side", "subcategory": "potato",    "is_veg": True,  "price_paise":  9900, "description": "Potato wedges with Indian spice mix"},
    {"name": "Onion Rings",              "category": "side", "subcategory": "fried",     "is_veg": True,  "price_paise":  9900, "description": "Crispy battered onion rings"},
    {"name": "Veg Nuggets (6 pc)",       "category": "side", "subcategory": "nuggets",   "is_veg": True,  "price_paise":  9900, "description": "Six crispy mixed-veg nuggets"},
    {"name": "Chicken Nuggets (6 pc)",   "category": "side", "subcategory": "nuggets",   "is_veg": False, "price_paise": 13900, "description": "Six breaded chicken nuggets"},
    {"name": "Chicken Nuggets (9 pc)",   "category": "side", "subcategory": "nuggets",   "is_veg": False, "price_paise": 18900, "description": "Nine breaded chicken nuggets"},
    {"name": "Chicken Wings (4 pc)",     "category": "side", "subcategory": "chicken",   "is_veg": False, "price_paise": 19900, "description": "Four crispy chicken wings, choice of sauce"},
    {"name": "Cheese Corn Nuggets",      "category": "side", "subcategory": "nuggets",   "is_veg": True,  "price_paise": 11900, "description": "Cheesy corn nuggets, six pieces"},
    {"name": "Garlic Bread (2 pc)",      "category": "side", "subcategory": "bread",     "is_veg": True,  "price_paise":  8900, "description": "Toasted garlic bread, two pieces"},

    # Drinks (all veg)
    {"name": "Coke (Regular)",           "category": "drink", "subcategory": "soda",     "is_veg": True,  "price_paise":  6900, "description": "Coca-Cola, regular size"},
    {"name": "Coke (Large)",             "category": "drink", "subcategory": "soda",     "is_veg": True,  "price_paise":  9900, "description": "Coca-Cola, large size"},
    {"name": "Sprite (Regular)",         "category": "drink", "subcategory": "soda",     "is_veg": True,  "price_paise":  6900, "description": "Sprite, regular size"},
    {"name": "Sprite (Large)",           "category": "drink", "subcategory": "soda",     "is_veg": True,  "price_paise":  9900, "description": "Sprite, large size"},
    {"name": "Fanta (Regular)",          "category": "drink", "subcategory": "soda",     "is_veg": True,  "price_paise":  6900, "description": "Fanta orange, regular size"},
    {"name": "Fanta (Large)",            "category": "drink", "subcategory": "soda",     "is_veg": True,  "price_paise":  9900, "description": "Fanta orange, large size"},
    {"name": "Iced Tea",                 "category": "drink", "subcategory": "tea",      "is_veg": True,  "price_paise":  7900, "description": "Lemon iced tea"},
    {"name": "Masala Chai",              "category": "drink", "subcategory": "tea",      "is_veg": True,  "price_paise":  4900, "description": "Hot Indian spiced tea"},
    {"name": "Filter Coffee",            "category": "drink", "subcategory": "coffee",   "is_veg": True,  "price_paise":  5900, "description": "South Indian filter coffee"},
    {"name": "Cold Coffee",              "category": "drink", "subcategory": "coffee",   "is_veg": True,  "price_paise":  9900, "description": "Chilled coffee with milk"},
    {"name": "Mango Shake",              "category": "drink", "subcategory": "shake",    "is_veg": True,  "price_paise": 12900, "description": "Thick mango milkshake"},
    {"name": "Chocolate Shake",          "category": "drink", "subcategory": "shake",    "is_veg": True,  "price_paise": 12900, "description": "Thick chocolate milkshake"},
    {"name": "Vanilla Shake",            "category": "drink", "subcategory": "shake",    "is_veg": True,  "price_paise": 12900, "description": "Thick vanilla milkshake"},
    {"name": "Fresh Lime Soda",          "category": "drink", "subcategory": "juice",    "is_veg": True,  "price_paise":  6900, "description": "Sweet & salty lime soda"},
    {"name": "Mineral Water",            "category": "drink", "subcategory": "water",    "is_veg": True,  "price_paise":  2000, "description": "500ml bottled water"},

    # Desserts — soft serves/sundaes are veg; baked goods contain egg => non-veg
    {"name": "Soft Serve Vanilla",       "category": "dessert", "subcategory": "icecream", "is_veg": True,  "price_paise":  4900, "description": "Vanilla soft serve cone"},
    {"name": "Soft Serve Chocolate",     "category": "dessert", "subcategory": "icecream", "is_veg": True,  "price_paise":  4900, "description": "Chocolate soft serve cone"},
    {"name": "Sundae (Strawberry)",      "category": "dessert", "subcategory": "icecream", "is_veg": True,  "price_paise":  8900, "description": "Vanilla sundae with strawberry sauce"},
    {"name": "Sundae (Chocolate)",       "category": "dessert", "subcategory": "icecream", "is_veg": True,  "price_paise":  8900, "description": "Vanilla sundae with chocolate sauce"},
    {"name": "Choco Lava Cake",          "category": "dessert", "subcategory": "cake",     "is_veg": False, "price_paise":  9900, "description": "Warm chocolate cake with molten center (contains egg)"},
    {"name": "Brownie",                  "category": "dessert", "subcategory": "cake",     "is_veg": False, "price_paise":  8900, "description": "Fudgy chocolate brownie (contains egg)"},
]


COMBOS: list[Combo] = [
    {"name": "Aloo Tikki Combo",      "is_veg": True,  "price_paise": 16900, "description": "Aloo Tikki Burger + Regular Fries + Coke (Regular)",
     "item_names": ["Aloo Tikki Burger", "Regular Fries", "Coke (Regular)"]},
    {"name": "Paneer Makhani Combo",  "is_veg": True,  "price_paise": 22900, "description": "Paneer Makhani Burger + Regular Fries + Coke (Regular)",
     "item_names": ["Paneer Makhani Burger", "Regular Fries", "Coke (Regular)"]},
    {"name": "Veggie Supreme Combo",  "is_veg": True,  "price_paise": 25900, "description": "Veggie Supreme Burger + Large Fries + Coke (Large)",
     "item_names": ["Veggie Supreme Burger", "Large Fries", "Coke (Large)"]},
    {"name": "Crispy Chicken Combo",  "is_veg": False, "price_paise": 22900, "description": "Crispy Chicken Burger + Regular Fries + Coke (Regular)",
     "item_names": ["Crispy Chicken Burger", "Regular Fries", "Coke (Regular)"]},
    {"name": "Grilled Chicken Combo", "is_veg": False, "price_paise": 24900, "description": "Grilled Chicken Burger + Regular Fries + Iced Tea",
     "item_names": ["Grilled Chicken Burger", "Regular Fries", "Iced Tea"]},
    {"name": "Tandoori Chicken Combo","is_veg": False, "price_paise": 25900, "description": "Tandoori Chicken Burger + Masala Wedges + Coke (Regular)",
     "item_names": ["Tandoori Chicken Burger", "Masala Wedges", "Coke (Regular)"]},
    {"name": "Maharaja Combo",        "is_veg": False, "price_paise": 34900, "description": "Chicken Maharaja Burger + Large Fries + Coke (Large)",
     "item_names": ["Chicken Maharaja Burger", "Large Fries", "Coke (Large)"]},
    {"name": "Double Chicken Combo",  "is_veg": False, "price_paise": 32900, "description": "Double Chicken Burger + Large Fries + Coke (Large)",
     "item_names": ["Double Chicken Burger", "Large Fries", "Coke (Large)"]},
    {"name": "Fish Fillet Combo",     "is_veg": False, "price_paise": 23900, "description": "Fish Fillet Burger + Regular Fries + Sprite (Regular)",
     "item_names": ["Fish Fillet Burger", "Regular Fries", "Sprite (Regular)"]},
    {"name": "Nuggets Combo (6 pc)",  "is_veg": False, "price_paise": 19900, "description": "Chicken Nuggets (6 pc) + Regular Fries + Coke (Regular)",
     "item_names": ["Chicken Nuggets (6 pc)", "Regular Fries", "Coke (Regular)"]},
    {"name": "Family Feast",          "is_veg": False, "price_paise": 79900, "description": "2 Chicken Maharaja + 2 Aloo Tikki + Large Fries x2 + Coke (Large) x2",
     "item_names": ["Chicken Maharaja Burger", "Aloo Tikki Burger", "Large Fries", "Coke (Large)"]},
    {"name": "Breakfast Express",     "is_veg": False, "price_paise": 14900, "description": "Egg & Cheese Burger + Masala Chai + Masala Wedges",
     "item_names": ["Egg & Cheese Burger", "Masala Chai", "Masala Wedges"]},
    # "Make it a meal" upsell bundles — added alongside a burger to upgrade to a meal.
    {"name": "Regular Meal",          "is_veg": True,  "price_paise": 12900, "description": "Regular Fries + Coke (Regular)",
     "item_names": ["Regular Fries", "Coke (Regular)"]},
    {"name": "Large Meal",            "is_veg": True,  "price_paise": 18900, "description": "Large Fries + Coke (Large)",
     "item_names": ["Large Fries", "Coke (Large)"]},
]


MODIFICATIONS: list[Modification] = [
    {"name": "extra cheese",        "price_delta_paise": 2900, "applies_to_category": "burger",  "description": "Add an extra slice of cheese"},
    {"name": "extra patty",         "price_delta_paise": 5900, "applies_to_category": "burger",  "description": "Add an extra patty"},
    {"name": "bacon",               "price_delta_paise": 4900, "applies_to_category": "burger",  "description": "Add bacon strips"},
    {"name": "jalapenos",           "price_delta_paise": 1500, "applies_to_category": "burger",  "description": "Add pickled jalapenos"},
    {"name": "no onion",            "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Remove onion"},
    {"name": "no tomato",           "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Remove tomato"},
    {"name": "no lettuce",          "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Remove lettuce"},
    {"name": "no mayo",             "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Remove mayonnaise (all variants — garlic / herb / bacon / mint mayo)"},
    {"name": "no cheese",           "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Remove cheese (all variants — cheddar, melted cheese)"},
    {"name": "no sauce",            "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Remove the burger's sauce (smoky / makhani / tartar / mint chutney / chipotle)"},
    {"name": "no jalapenos",        "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Remove jalapenos"},
    {"name": "extra spicy",         "price_delta_paise":    0, "applies_to_category": "burger",  "description": "Add extra peri-peri / chilli"},
    {"name": "no salt",             "price_delta_paise":    0, "applies_to_category": "side",    "description": "Hold the salt"},
    {"name": "extra seasoning",     "price_delta_paise":    0, "applies_to_category": "side",    "description": "Extra peri-peri / masala seasoning"},
    {"name": "ketchup",             "price_delta_paise":    0, "applies_to_category": "side",    "description": "Add ketchup packet(s)"},
    {"name": "mayo dip",            "price_delta_paise": 1500, "applies_to_category": "side",    "description": "Add a mayo dip"},
    {"name": "no ice",              "price_delta_paise":    0, "applies_to_category": "drink",   "description": "Serve with no ice"},
    {"name": "less sugar",          "price_delta_paise":    0, "applies_to_category": "drink",   "description": "Half sugar"},
    {"name": "no sugar",            "price_delta_paise":    0, "applies_to_category": "drink",   "description": "Sugar-free"},
    {"name": "extra hot",           "price_delta_paise":    0, "applies_to_category": "drink",   "description": "Serve extra hot (tea/coffee)"},
    {"name": "takeaway",            "price_delta_paise":    0, "applies_to_category": None,      "description": "Pack for takeaway"},
]


PROMOTIONS: list[Promotion] = [
    {"name": "Highway Happy Hour",
     "description": "10% off any combo between 3pm and 6pm",
     "discount_type": "percent", "discount_value": 10},
    {"name": "Two-Burger Tuesday",
     "description": "Any two veg burgers for ₹199 (Tuesdays only)",
     "discount_type": "combo_price_paise", "discount_value": 19900,
     "condition": {"type": "any_n_in_category", "n": 2, "category": "burger", "is_veg": True}},
    {"name": "Trucker Tea Combo",
     "description": "Masala Chai + Garlic Bread for ₹99",
     "discount_type": "combo_price_paise", "discount_value": 9900,
     "condition": {"type": "specific_items", "items": ["Masala Chai", "Garlic Bread (2 pc)"]}},
    {"name": "Family Feast Discount",
     "description": "Flat ₹100 off the Family Feast combo",
     "discount_type": "flat_paise", "discount_value": 10000},
    {"name": "Student Special",
     "description": "15% off on orders above ₹300 with valid student ID",
     "discount_type": "percent", "discount_value": 15,
     "min_subtotal_paise": 30000},
    {"name": "Maharaja Monday",
     "description": "Maharaja Combo at ₹299 on Mondays",
     "discount_type": "combo_price_paise", "discount_value": 29900,
     "condition": {"type": "specific_items", "items": ["Maharaja Combo"]}},
]
