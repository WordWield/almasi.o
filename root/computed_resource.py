# ==============================================================================
# COMPUTED RESOURCE
# ==============================================================================
# PURPOSE:
# Retain a computed value and its observed O dependency scope.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Cached value and observed dependencies.
# Delegates: Dependency matching to Sync and listener delivery to Resource.
# ==============================================================================

import threading

from almasi import o


class ComputedResource(o.Resource):

	# ==========================================================================
	# FRAMEWORK METHODS
	# ==========================================================================

	# Start without a cached value or an inferred dependency scope.
	# ----------------------------------------------------------------------
	def __init__(self):
		self.dependencies      = frozenset()
		self._value            = o.Undefined
		self._candidate        = o.Undefined
		self._observed_changes = o.Undefined
		self._lock             = threading.RLock()

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

	# Stage assignment inside a tracked scope; otherwise replace the value.
	# ----------------------------------------------------------------------
	@value.setter
	def value(self, value):
		with self._lock:
			if self._observed_changes is o.Undefined:
				self._value = value
			else:
				self._candidate = value

	# Observe dependencies in Sync while this resource has listeners.
	# ----------------------------------------------------------------------
	@property
	def _observe(self):
		return o.services.Sync.observe

	# Start one non-replayable computation without exposing partial values.
	# ----------------------------------------------------------------------
	def _begin(self):
		with self._lock:
			if self._observed_changes is o.Undefined:
				self._candidate        = o.Undefined
				self._observed_changes = set()
			else:
				raise RuntimeError('Computed resource is already being observed')

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

	# Commit under the source's publication lock to close the observation gap.
	# ----------------------------------------------------------------------
	def _commit(self, reads, sync):
		sync.commit_resource(self, frozenset(reads))

	# Validate the completed observation and publish the same resource instance.
	# The source holds its lock before entering the resource's own lock.
	# ----------------------------------------------------------------------
	def _publish(self, identifiers, sync):
		with self._lock:
			changes = self._observed_changes

			if changes is not None and not changes & identifiers:
				sync.update_resource(self, identifiers)
				self.dependencies = identifiers
				self._value       = self._candidate
			else:
				raise RuntimeError('Computed resource changed during read; try again')

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

	# Invalidate the cached value once before notifying its listeners.
	# ----------------------------------------------------------------------
	def update(self, changed=None):
		with self._lock:
			self._value = o.Undefined

		super().update(changed)
