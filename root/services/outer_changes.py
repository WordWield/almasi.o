# ==============================================================================
# OUTER CHANGES SERVICE
# ==============================================================================
# PURPOSE:
# Apply interprocess invalidations to the receiving ontology.
#
# RESPONSIBILITY BOUNDARIES:
# Owns: Reception of remote changes and critical cache invalidation policy.
# Delegates: Wire delivery to Transport, cache storage to Cache, and ordered
# in-process notifications to InnerChanges.
# ==============================================================================

import logging
import os

from almasi import o


class OuterChanges(o.Singleton):

	# ======================================================================
	# PUBLIC METHODS
	# ======================================================================

	# Queue an incoming change without echoing it to the sending process.
	# ----------------------------------------------------------------------
	def receive(self, ids):
		o.services.InnerChanges.publish_change(ids, local=False)

	# Invalidate remote owners before InnerChanges notifies consumers.
	# ----------------------------------------------------------------------
	def invalidate(self, ids):
		try:
			o.services.Cache.invalidate(ids)
		except Exception:
			logging.exception('Critical cache invalidation failure')
			os._exit(1)
