API reference
=============

The public modules, grouped by side. The build side reads the source vocabularies; the runtime
side reads only the shipped ``brand_ingredient_map.csv``.

Runtime
-------

.. automodule:: ruim2rxnorm.normalize
   :members:

.. automodule:: ruim2rxnorm.lookup
   :members:

.. automodule:: ruim2rxnorm.outputs
   :members:

.. automodule:: ruim2rxnorm.cli
   :members:

.. automodule:: ruim2rxnorm.rxrisk
   :members:

.. automodule:: ruim2rxnorm.rxrisk_cli
   :members:

Build (ETL)
-----------

.. automodule:: ruim2rxnorm.etl.athena_io
   :members:

.. automodule:: ruim2rxnorm.etl.ruim_io
   :members:

.. automodule:: ruim2rxnorm.etl.resolve
   :members:

.. automodule:: ruim2rxnorm.etl.build_refs
   :members:
