"""Exception hierarchy of the shop package.

Every error raised intentionally by the package derives from :class:`ShopError`,
so callers (CLI, HTTP layer) can catch a single base class.
"""


class ShopError(Exception):
    """Base class for all domain errors of the shop."""


class ValidationError(ShopError, ValueError):
    """Input data is malformed or violates a domain invariant."""


class UnknownProductError(ShopError):
    """A product with the given SKU is not present in the catalog or cart."""

    def __init__(self, sku: str) -> None:
        super().__init__(f"unknown product: {sku!r}")
        self.sku = sku


class EmptyCartError(ShopError):
    """An operation requires at least one line in the cart."""


class OrderNotFoundError(ShopError):
    """No order with the given id exists in the store."""

    def __init__(self, order_id: str) -> None:
        super().__init__(f"order not found: {order_id!r}")
        self.order_id = order_id


class InvalidOrderStateError(ShopError):
    """The requested transition is not allowed for the current order status."""


class PromoError(ShopError):
    """Base class for promo code problems."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class UnknownPromoCodeError(PromoError):
    """No promo code with this name is registered."""


class PromoExpiredError(PromoError):
    """The promo code is outside of its validity window (not started yet or already over)."""


class PromoConditionsError(PromoError):
    """The promo code exists and is active but cannot be applied to this order."""
