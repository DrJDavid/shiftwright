"""Static catalog: departments, roles, penalties, nicknames, names. From briefs/WS4-scenarios.md."""
from __future__ import annotations

DEPARTMENTS: list[tuple[str, str]] = [
    ("front_of_store", "Front of Store"),
    ("general_merchandise", "General Merchandise"),
    ("grocery", "Grocery"),
    ("fulfillment", "Fulfillment"),
    ("asset_protection", "Asset Protection"),
    ("receiving", "Receiving"),
    ("leadership", "Leadership"),
]

# role_id: (department_id, name, min_age, gap_penalty_per_hour, description)
ROLES: dict[str, tuple[str, str, int, float, str]] = {
    "leader_on_duty": ("leadership", "Leader on Duty", 0, 100.0, "Leader responsible for the building while open."),
    "guest_service_desk": ("front_of_store", "Guest Service Desk", 0, 80.0, "Returns, questions, pickups."),
    "cashier": ("front_of_store", "Cashier", 0, 60.0, "Front lanes and self-checkout."),
    "cart_attendant": ("front_of_store", "Cart Attendant", 0, 25.0, "Carts and lot."),
    "drive_up": ("front_of_store", "Drive Up", 0, 50.0, "Brings online orders to cars."),
    "softlines": ("general_merchandise", "Softlines", 0, 25.0, "Apparel and home textiles floor."),
    "hardlines": ("general_merchandise", "Hardlines", 0, 25.0, "Electronics, toys, sporting goods floor."),
    "fitting_room": ("general_merchandise", "Fitting Room", 0, 15.0, "Fitting room and go-backs."),
    "grocery_stock": ("grocery", "Grocery Stock", 0, 30.0, "Stocks and fronts grocery."),
    "order_picker": ("fulfillment", "Order Picker", 0, 45.0, "Picks online orders."),
    "ap_specialist": ("asset_protection", "AP Specialist", 0, 40.0, "Asset protection on the floor."),
    "truck_unload": ("receiving", "Truck Unload", 0, 70.0, "Unloads the trailer and sorts freight."),
    "backroom": ("receiving", "Backroom", 0, 30.0, "Backstock and pulls."),
    "pit_operator": ("receiving", "PIT Operator", 18, 70.0, "Operates powered industrial trucks."),
}

ROLE_TAGS: dict[str, list[str]] = {"pit_operator": ["powered_industrial_truck"]}

SMALL_ROLES = [
    "leader_on_duty", "guest_service_desk", "cashier", "drive_up", "hardlines",
    "grocery_stock", "truck_unload", "backroom", "pit_operator",
]

NICKNAMES: dict[str, list[str]] = {
    "front_of_store": ["the front end", "front of store", "the front"],
    "general_merchandise": ["GM", "the floor", "softlines and hardlines"],
    "grocery": ["food", "grocery", "the food side"],
    "fulfillment": ["fulfillment", "the online team", "the pickers"],
    "asset_protection": ["AP", "asset protection"],
    "receiving": ["the back", "receiving", "the backroom crew"],
    "leadership": ["the LODs", "the leaders", "the leadership team"],
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

FIRST_NAMES = [
    "Avery", "Bailey", "Cameron", "Dakota", "Emerson", "Finley", "Gray", "Harper", "Indigo", "Jamie",
    "Kendall", "Logan", "Micah", "Noel", "Oakley", "Parker", "Quinn", "Reese", "Sage", "Taylor",
    "Uma", "Val", "Wren", "Xavi", "Yael", "Zion", "Ari", "Blake", "Charlie", "Devon",
    "Eden", "Frankie", "Gabe", "Hayden", "Ira", "Jules", "Kai", "Lane", "Marlowe", "Nico",
    "Ollie", "Peyton", "Remy", "Skyler", "Toni", "Rowan", "Sasha", "Tatum", "Robin", "Shay",
    "Ellis", "Jesse", "Kerry", "Lee", "Max", "Pat", "Ray", "Sam", "Terry", "Dana",
]
LAST_NAMES = [
    "Garcia", "Smith", "Johnson", "Martinez", "Brown", "Lopez", "Davis", "Hernandez", "Wilson", "Moore",
    "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Gonzalez", "Clark", "Lewis",
    "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter",
]

TIMEZONES = {
    "CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "OR": "America/Los_Angeles",
    "NV": "America/Los_Angeles", "AZ": "America/Phoenix", "CO": "America/Denver",
    "UT": "America/Denver", "NM": "America/Denver", "NY": "America/New_York",
    "NJ": "America/New_York", "PA": "America/New_York", "MA": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "OH": "America/New_York",
    "MI": "America/Detroit", "IL": "America/Chicago", "TX": "America/Chicago",
}
