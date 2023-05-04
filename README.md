# dotinp

A python parser for Abaqus.inp (**dotinp**) files. 
This parser enables converting a .inp file to a python object tree which can be manipulated and queried.
Therefore this script helps auto-generating and altering finite element models (FEMs) programmatically.

## Fully Supported (completely parameterized): 
* Orientation
* Node
* Element
* Elsets
* Nsets

## Partially Supported (partially or not parameterized but represented by an unique object):
* Assembly
* Part
* Step
* Include 
* Material
* Section (Beam/ solid/ shell)
* Parameter
* ...

## Operations:
* Delete set: delete a list of elsets/nsets and all elements/nodes which are unique to these sets.
