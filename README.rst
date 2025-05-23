SDN fixtures
============

Declarative network setup using DOT format — proof of concept.
Still in the early stages; use at your own risk.

Install in a venv:

.. code::

   pip install -r https://svinota.github.io/sdn-fixtures/requirements.lekplats.txt

Display the definition:

.. code::

   curl https://svinota.github.io/sdn-fixtures/examples/004-veth-netns-vrf.dot | xdot -

Apply the definition:

.. code::

   pyroute2-dot up https://svinota.github.io/sdn-fixtures/examples/004-veth-netns-vrf.dot

