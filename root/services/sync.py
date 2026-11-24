# ==============================================================================
# SYNC SERVICE
# ==============================================================================
# PURPOSE:
# Queue committed changes from memory and transport through one worker.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Resource dependency matching and committed change delivery.
# Delegates: Listener registration and callback dispatch to Resource.
# ==============================================================================

import logging
import os
import threading

from functools import partial
from queue     import SimpleQueue
from time      import sleep

from almasi import o


class Sync(o.Singleton):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Normalize a watch scope without retaining the caller's mutable set.
	# ----------------------------------------------------------------------
	def _scope(self, identifiers):
		if identifiers is None:
			scope = None
		elif isinstance(identifiers, (set, frozenset)):
			scope = frozenset(identifiers)
		else:
			raise TypeError('Subscription identifiers must be a set, frozenset or None')

		return scope

	# Keep one index entry per observed resource and identifier.
	# ----------------------------------------------------------------------
	def _reindex(self, identity, before, after):
		if before is None:
			self._broad.discard(identity)
		else:
			for identifier in before if after is None else before - after:
				bucket = self._by_id[identifier]
				bucket.discard(identity)

				if not bucket:
					del self._by_id[identifier]

		if after is None:
			self._broad.add(identity)
		else:
			for identifier in after if before is None else after - before:
				self._by_id.setdefault(identifier, set()).add(identity)

	# Snapshot scopes for broad and dense invalidations.
	# ----------------------------------------------------------------------
	def _refresh(self):
		self._snapshot = tuple(self._resources.values())

	# Deliver through the sparse/dense index without rebuilding matched entries.
	# ----------------------------------------------------------------------
	def _dispatch(self, changed, local=True):
		changes = changed if changed is None or isinstance(changed, frozenset) else self._scope(changed)

		if changes is None or len(self._snapshot) <= 16:
			candidates = self._snapshot
		elif changes:
			with self._observation_lock:
				potential = len(self._broad) + sum(
					len(self._by_id.get(identifier, ())) for identifier in changes
				)

				if potential * 2 >= len(self._resources):
					candidates = self._snapshot
				else:
					matched = set(self._broad)

					for identifier in changes:
						matched.update(self._by_id.get(identifier, ()))

					candidates = sorted(self._resources[identity] for identity in matched)
		else:
			candidates = ()

		for _, resource, identifiers, local_only in candidates:
			if local or not local_only:
				matching = None if changes is None else (
					changes if identifiers is None else changes & identifiers
				)

				if changes is None or matching:
					resource.update(matching)

	# One delivery point for local and external invalidations.
	# ----------------------------------------------------------------------
	def _update(self, ids, local=True):
		if not local:
			try:
				o.services.Cache.invalidate(ids)
			except Exception:
				logging.exception('Critical cache invalidation failure')
				os._exit(1)

		self._dispatch(ids, local)

	# Merge adjacent invalidations without changing local/remote ordering.
	# ----------------------------------------------------------------------
	def _deliver(self, events):
		changed = set()
		local   = events[0][1]

		for ids, origin in events:
			if origin != local:
				self._update(None if changed is None else frozenset(changed), local=local)
				changed = set()
				local   = origin

			if ids is None:
				changed = None
			elif changed is not None:
				changed.update(ids)

		self._update(None if changed is None else frozenset(changed), local=local)

	# Wait for work, then collect a bounded burst without busy polling.
	# ----------------------------------------------------------------------
	def _run_worker_loop(self):
		while True:
			first = self._queue.get()
			sleep(0.0001)
			events = [first]

			for _ in range(self._queue.qsize()):
				events.append(self._queue.get_nowait())

			self._deliver(events)

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Create one worker per ontology; there is no pre-commit fallback.
	# ----------------------------------------------------------------------
	def initialize(self):
		# Only the worker handles delivery.
		# --------------------------------------------------------------
		self._observation_lock = threading.RLock()
		self._resources        = {}
		self._snapshot         = ()
		self._by_id            = {}
		self._broad            = set()
		self._next_order       = 0
		self._commits          = o.Resource()
		self._queue            = SimpleQueue()

		self._worker = threading.Thread(
			target = self._run_worker_loop,
			name   = 'o-sync',
			daemon = True,
		)
		self._worker.start()

	# Create a computed resource without assigning external identity.
	# ----------------------------------------------------------------------
	def resource(self):
		return o.ComputedResource()

	# Observe a resource once, regardless of its number of listeners.
	# ----------------------------------------------------------------------
	def observe(
		self,
		resource,
		identifiers = None,
		local_only  = False
	):
		with self._observation_lock:
			if isinstance(resource, o.ComputedResource):
				identity      = resource
				is_unresolved = resource.value is o.Undefined and not resource.dependencies
				identifiers   = None if is_unresolved else resource.dependencies
			else:
				identity = (identifiers, local_only)

			if resource.is_subscribed():
				if identity not in self._resources:
					self._resources[identity] = (self._next_order, resource, identifiers, local_only)
					self._next_order += 1
					self._reindex(identity, frozenset(), identifiers)
					self._refresh()
			elif identity in self._resources and self._resources[identity][1] is resource:
				_, _, before, _ = self._resources.pop(identity)
				self._reindex(identity, before, frozenset())
				self._refresh()

	# Subscribe to raw owner-ID invalidations without creating a computed value.
	# ----------------------------------------------------------------------
	def subscribe(
		self,
		ids        = None,
		callback   = None,
		local_only = False
	):
		if type(local_only) is bool:
			if callable(ids) and callback is None:
				callback = ids
				ids      = None

			scope    = self._scope(ids)
			identity = (scope, local_only)

			with self._observation_lock:
				entry    = self._resources.get(identity)
				resource = entry[1] if entry is not None else o.Resource(
					partial(self.observe, identifiers=scope, local_only=local_only)
				)

				cancel = partial(resource.unsubscribe, resource.subscribe(callback))
		else:
			raise TypeError('local_only must be bool')

		return cancel

	# Observe committed changes with their origin before asynchronous delivery.
	# ----------------------------------------------------------------------
	def watch_commits(self, callback):
		with self._observation_lock:
			cancel = partial(self._commits.unsubscribe, self._commits.subscribe(callback))

		return cancel

	# Commit the value and its dependencies with no gap against publication.
	# The source lock precedes the resource lock in both competing operations.
	# ----------------------------------------------------------------------
	def commit_resource(self, resource, identifiers):
		with self._observation_lock:
			resource._publish(identifiers, self)

	# Replace the observed resource scope without touching its listeners.
	# ----------------------------------------------------------------------
	def update_resource(self, resource, identifiers):
		with self._observation_lock:
			if resource in self._resources:
				order, _, before, local_only = self._resources[resource]

				if before != identifiers:
					self._reindex(resource, before, identifiers)
					self._resources[resource] = (order, resource, identifiers, local_only)
					self._refresh()

	# Confirm commits synchronously before queuing asynchronous invalidations.
	# ----------------------------------------------------------------------
	def publish_change(self, ids, local=True):
		with self._observation_lock:
			self._commits.update((ids, local))

			if not local or self._resources:
				self._queue.put((ids, local))
