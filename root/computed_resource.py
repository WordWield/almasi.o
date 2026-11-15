# ==============================================================================
# COMPUTED RESOURCE
# ==============================================================================
# Cache one observed value and delegate invalidation subscriptions to O Sync.
# ==============================================================================

import threading
import weakref

import o


class ComputedResource(o.Module, o.Resource):

	# ==========================================================================
	# FRAMEWORK METHODS
	# ==========================================================================

	# Start without a value or observed dependencies.
	# ----------------------------------------------------------------------
	def __init__(self, identifier, sync=None):
		self.id             = identifier
		self.value          = o.Undefined
		self.dependencies   = None
		self._sync          = o.services.Sync if sync is None else sync
		self._subscriptions = weakref.WeakSet()
		self._lock          = threading.RLock()

	# ==========================================================================
	# PRIVATE METHODS
	# ==========================================================================

	# Invalidate the current cache before notifying the interested listener.
	# ----------------------------------------------------------------------
	def _changed(self, changed, callback):
		with self._lock:
			self.value = o.Undefined

		callback(changed)

	# ==========================================================================
	# PUBLIC METHODS
	# ==========================================================================

	# Return the cached value; Web owns any needed controller invocation.
	# ----------------------------------------------------------------------
	def read(self):
		return self.value

	# Keep each listener independently registered in the existing Sync service.
	# ----------------------------------------------------------------------
	def subscribe(self, callback):
		if not callable(callback):
			raise TypeError('Subscription callback must be callable')

		with self._lock:
			identifiers = self.dependencies

			def changed(ids):
				self._changed(ids, callback)

			subscription = self._sync.subscribe(identifiers, changed)
			self._subscriptions.add(subscription)

		return subscription

	# Install a successfully observed value and its dependency scope together.
	# ----------------------------------------------------------------------
	def replace(self, value, identifiers):
		dependencies = frozenset(identifiers)

		with self._lock:
			before = self.dependencies
			updated = []

			try:
				for subscription in tuple(self._subscriptions):
					if subscription._active:
						subscription.update(dependencies)
						updated.append(subscription)
			except BaseException:
				for subscription in reversed(updated):
					if subscription._active:
						subscription.update(before)

				raise
			else:
				self.dependencies = dependencies
				self.value        = value
