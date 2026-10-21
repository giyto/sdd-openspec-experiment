"""Order calculation service of the online shop."""

from .catalog import Cart, CartLine, Catalog, Category, Product
from .clock import Clock, FixedClock, SystemClock
from .errors import ShopError, ValidationError
from .orders import Order, OrderService, OrderStatus, OrderStore
from .pricing import OrderTotal, ShippingPolicy, TaxPolicy, calculate_total
from .promo import DiscountKind, PromoCode, PromoRegistry

__all__ = [
    "Cart",
    "CartLine",
    "Catalog",
    "Category",
    "Clock",
    "DiscountKind",
    "FixedClock",
    "Order",
    "OrderService",
    "OrderStatus",
    "OrderStore",
    "OrderTotal",
    "Product",
    "PromoCode",
    "PromoRegistry",
    "ShippingPolicy",
    "ShopError",
    "SystemClock",
    "TaxPolicy",
    "ValidationError",
    "calculate_total",
]

__version__ = "1.4.0"
