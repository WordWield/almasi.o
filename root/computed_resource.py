# ==============================================================================
# COMPUTED RESOURCE
# ==============================================================================
# Retain one identified result and its observed O dependency scope.
# ==============================================================================

import threading

import o


class ComputedResource(o.Resource):

	# ==========================================================================
	# FRAMEWORK METHODS
	# ==========================================================================

	# Start without a cached value or an inferred dependency scope.
	# ----------------------------------------------------------------------
	def __init__(self, identifier):
		self.id               = identifier
		self.dependencies     = frozenset()
		self._value           = o.Undefined
		self._candidate       = o.Undefined
		self._observed_changes = o.Undefined
		self._lock            = threading.RLock()

	# ==========================================================================
	# PRIVATE METHODS
	# ==========================================================================

	# Stage the result until the tracked read scope completes successfully.
	# ----------------------------------------------------------------------
	@property
	def value(self):
		with self._lock:
			result = self._value

		return result

	@value.setter
	def value(self, value):
		with self._lock:
			if self._observed_changes is o.Undefined:
				self._value = value
			else:
				self._candidate = value

	# Mark an observed value stale without changing its subscription scope.
	# ----------------------------------------------------------------------
	def _invalidate(self):
		with self._lock:
			self._value = o.Undefined

	# Start one non-replayable computation without exposing partial values.
	# ----------------------------------------------------------------------
	def _begin(self):
		with self._lock:
			if self._observed_changes is not o.Undefined:
				raise RuntimeError('Computed resource is already being observed')

			self._candidate        = o.Undefined
			self._observed_changes = set()

	# Collect live invalidations for all IDs, including newly read owners.
	# ----------------------------------------------------------------------
	def _observe_change(self, identifiers):
		with self._lock:
			changes = self._observed_changes

			if changes is not o.Undefined:
				if identifiers is None:
					self._observed_changes = None
				elif changes is not None:
					changes.update(identifiers)

	# Publish a completed result and update live source registrations.
	# ----------------------------------------------------------------------
	def _commit(self, reads, sync):
		identifiers = frozenset(reads)

		with self._lock:
			changes = self._observed_changes

			if changes is None or changes & identifiers:
				raise RuntimeError('Computed resource changed during read; try again')

			sync.update_resource(self, identifiers)
			self.dependencies = identifiers
			self._value       = self._candidate

	# Restore idle state even after an exception or rejected computation.
	# ----------------------------------------------------------------------
	def _end(self):
		with self._lock:
			self._candidate        = o.Undefined
			self._observed_changes = o.Undefined

	# ==========================================================================
	# PUBLIC METHODS
	# ==========================================================================

	# Return the cached value without invoking the computation.
	# ----------------------------------------------------------------------
	def read(self):
		return self.value

	# Register each listener separately through the O Sync source.
	# ----------------------------------------------------------------------
	def subscribe(self, callback):
		return o.services.Sync.subscribe(self, callback)
