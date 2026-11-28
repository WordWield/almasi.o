# ==============================================================================
# INNER CHANGES SERVICE
# ==============================================================================
# PURPOSE:
# Deliver committed local and remote owner changes inside one ontology.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Resource dependency matching and committed change delivery.
# Delegates: Remote cache invalidation to OuterChanges and listener delivery
# to Resource.
# ==============================================================================

import threading

from functools import partial
from queue     import SimpleQueue
from time      import sleep

from almasi import o


class InnerChanges(o.Singleton):

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
				if changes is None:
					resource.update(None)
				elif changes:
					if identifiers is None:
						resource.update(changes)
					elif not changes.isdisjoint(identifiers):
						resource.update(changes & identifiers)

	# One delivery point for local and external invalidations.
	# ----------------------------------------------------------------------
	def _update(self, ids, local=True):
		if not local:
			o.services.OuterChanges.invalidate(ids)

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

	# Release the synchronous observation resource after its final listener.
	# ----------------------------------------------------------------------
	def _unwatch_commits(self, subscription_id):
		with self._observation_lock:
			if self._commits is not None:
				self._commits.unsubscribe(subscription_id)

				if not self._commits.is_subscribed():
					self._commits = None

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
		self._commits          = None
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
		return o.resources.Computed()

	# Reconcile registration and dependency changes through the same index.
	# ----------------------------------------------------------------------
	def observe(
		self,
		resource,
		identifiers = o.Undefined,
		local_only  = False
	):
		with self._observation_lock:
			is_computed = isinstance(resource, o.resources.Computed)
			identity    = resource if is_computed else (identifiers, local_only)
			entry       = self._resources.get(identity)

			if resource.is_subscribed():
				if entry is None:
					if is_computed and identifiers is o.Undefined:
						is_unresolved = resource.value is o.Undefined and not resource.dependencies
						identifiers   = None if is_unresolved else resource.dependencies

					self._resources[identity] = (self._next_order, resource, identifiers, local_only)
					self._next_order += 1
					self._reindex(identity, frozenset(), identifiers)
				elif identifiers is not o.Undefined:
					order, _, before, origin = entry

					if before != identifiers:
						self._resources[identity] = (order, resource, identifiers, origin)
						self._reindex(identity, before, identifiers)
			elif entry is not None and entry[1] is resource:
				del self._resources[identity]
				self._reindex(identity, entry[2], frozenset())

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
			resource        = self._commits if self._commits is not None else o.Resource()
			subscription_id = resource.subscribe(callback)
			self._commits   = resource
			cancel          = partial(self._unwatch_commits, subscription_id)

		return cancel

	# Commit the value and its dependencies with no gap against publication.
	# The source lock precedes the resource lock in both competing operations.
	# ----------------------------------------------------------------------
	def commit_resource(self, resource, identifiers):
		with self._observation_lock:
			resource._publish(identifiers, self)

	# Confirm commits synchronously before queuing asynchronous invalidations.
	# ----------------------------------------------------------------------
	def publish_change(self, ids, local=True):
		with self._observation_lock:
			if self._commits is not None:
				self._commits.update((ids, local))

			if not local or self._resources:
				self._queue.put((ids, local))
