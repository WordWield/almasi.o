# ==============================================================================
# GARBAGE SERVICE
# ==============================================================================
# Track instances reachable from the persistent root and reclaim unretained data.
# ==============================================================================

from almasi import o


class Garbage(o.Singleton):

	# ======================================================================
	# PRIVATE METHODS
	# ======================================================================

	# Treat the persistent root and explicit root-level calls as reachable.
	# ----------------------------------------------------------------------
	def _is_owner_reachable(self, owner):
		return (
			owner is None
			or isinstance(owner, o.T.V)
			or self.refcounts.get(owner.id, 0) > 0
		)

	# Retain an instance and its descendants only when it first becomes live.
	# ----------------------------------------------------------------------
	def _on_instance_link(self, instance):
		old_count = self.refcounts.get(instance.id, 0)
		count     = old_count + 1

		self.refcounts.set(instance.id, count, instance.id)
		self.garbage.unset(instance.id, instance.id)

		if old_count == 0:
			for child in instance.__get_outgoing_references__():
				self._on_instance_link(child)

	# Release descendants only when the last rooted reference disappears.
	# ----------------------------------------------------------------------
	def _on_instance_unlink(self, instance):
		old_count = self.refcounts.get(instance.id, 0)
		count     = max(old_count - 1, 0)

		if count == 0:
			self.refcounts.unset(instance.id, instance.id)
			self.garbage.set(instance.id, instance.__proto__, instance.id)

			if old_count == 1:
				for child in instance.__get_outgoing_references__():
					self._on_instance_unlink(child)
		else:
			self.refcounts.set(instance.id, count, instance.id)

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Resume the persistent garbage queues and collect previously marked data.
	# ----------------------------------------------------------------------
	def initialize(self):
		memory = o.services.Memory

		self.refcounts = memory.zone('garbage/refcounts/')
		self.garbage   = memory.zone('garbage/items/')

		self.collect()

	# Mark new non-root instances for deletion unless they become reachable.
	# ----------------------------------------------------------------------
	def on_instance_create(self, cls, id, proto):
		if cls is not o.T.V:
			self.garbage.set(id, proto, id)

	# Count new edges only when the containing object is reachable.
	# ----------------------------------------------------------------------
	def on_instance_link(self, instance, owner=None):
		if self._is_owner_reachable(owner):
			with o.services.Memory.write():
				self._on_instance_link(instance)

	# Remove edges only when they were counted through a reachable owner.
	# ----------------------------------------------------------------------
	def on_instance_unlink(self, instance, owner=None):
		if self._is_owner_reachable(owner):
			with o.services.Memory.write():
				self._on_instance_unlink(instance)

	# Delete marked instances and their ID mappings at the next startup.
	# ----------------------------------------------------------------------
	def collect(self):
		memory = o.services.Memory

		with memory.write():
			for id, proto in self.garbage.items():
				instance_id = int(id)
				class_id    = o.services.Id.hash(proto.rsplit('.', 1)[0])

				if o.TREE_MODE:
					memory.unset(f'tree/parents/{instance_id}', instance_id)

				memory.unset(proto, (instance_id, class_id))
				memory.zone(f'{proto}.').clear()
				o.services.Id.unset(instance_id)

			self.clear()

	# Remove garbage queue entries after their persistent records are deleted.
	# ----------------------------------------------------------------------
	def clear(self):
		self.garbage.clear(int(id) for id in self.garbage.keys())
