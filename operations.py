def isnotebook():
    try:
        shell = get_ipython().__class__.__name__
        if shell == 'ZMQInteractiveShell':
            return True   # Jupyter notebook or qtconsole
        elif shell == 'TerminalInteractiveShell' or shell == 'SpyderShell':
            return False  # Terminal running IPython
        else:
            return False  # Other type (?)
    except NameError:
        return False      # Probably standard Python interpreter

codedir = None
if (isnotebook()):
    codedir = os.path.dirname(os.path.abspath(''))
else:
    codedir = os.path.dirname(os.path.realpath(__file__))

sys.path.append(codedir)

from parser import *

def unique(iterable):
    unique_list = []
    for i in iterable:
        if i not in unique_list:
            unique_list.append(i)
    return unique_list
    
def findreferencingsets(element, root):
    eln = None
    elsets = []
    for elemnode in root.query("** > Element"):
        elem_df = elemnode.todataframe()
        if ((elem_df.index == element).any()):
            eln =  elemnode.getheader()
    
    for iset in root.query("** > Elset|Nset"):
        if element in iset.toarray():
            elsets += [iset]
    return eln, elsets
    
def findreferencingelements(nodes, root, excludeelements = [], log = False):
    """
        Find which elements reference the given nodes
    """
    references = {}
    for elemnode in root.query("** > Element"):
        elem_df = elemnode.todataframe()
        for n in nodes:
            nodeoccurences = elem_df.loc[(elem_df == n).any(axis=1),:]
            outset = (nodeoccurences.index.isin(excludeelements) == False)
            if (outset.any()):
                if (n in references.keys()):
                    references[n] += nodeoccurences.index[outset].values.tolist()
                else:
                    references[n] = nodeoccurences.index[outset].values.tolist()
    if (log):
        import json
        print("Following nodes are referenced by elements:")
        for k, v in references.items():
            print(("{:>7s}: {:s}").format(str(k), str(v)))
    return references
    
def deletesets(sets, root = None, insetelements = True, insetnodes = True, log = False, dodelete=True):
    """
     Give a list of elsets/nsets and return all elements and nodes that can be safely deleted,
     as they are not being referenced by other elsets/nsets
    """
    if not isinstance(sets, list):
        sets = [sets]
    
    if (root == None):
        root = sets[0].getroot()
            
    elements = []
    for elset in sets:
        if (isinstance(elset, BlockReaderElset)):
            elements += list(elset.toarray())
        elif (not isinstance(elset, BlockReaderNset)):
            raise ValueError("Unknown datatype" + str(elset))
    
    if (log):
        print("\n".join(map(str, sets)))
    deletableelements = unique(elements)
    sharedelements = []
    nelem = len(elements)
    
    if insetelements:
        interferingsets = []
        for otherset in root.query("** > Elset"):
            if (otherset not in sets):
                otherelements = otherset.toarray()
                cross_section = np.intersect1d(deletableelements, otherelements)
                sharedelements += [i for i in deletableelements if i in cross_section]
                deletableelements = [i for i in deletableelements if i not in cross_section] 
                if (len(cross_section) > 0 and log):
                    print("{:d} elements are shared with other elset {:s}".format(len(cross_section), otherset.header.getproperty("elset")))
        if (log):
            print("Deleting elements: {:d} unique elements, {:d} elements were shared with other sets".format(len(deletableelements), nelem - len(deletableelements)))
    elif log:
        print("Deleting elements: {:d} elements".format(nelem))
    
    nodes = []
    for elemnode in root.query("** > Element"):
        elem_df = elemnode.todataframe()
        xs = [_el for _el in deletableelements if _el in elem_df.index]
        if (xs):
            n = elem_df.loc[xs,:]
            nodes += list(n.values.flatten())
    
    for nset in sets:
        if isinstance(nset, BlockReaderNset):
            nodes += list(nset.toarray())
    
    deletablenodes = unique(nodes)
    sharednodes = []
    nnodes = len(nodes)
    if (insetnodes):
        # exclude the node if other elements also reference the node
        cross_section = []
        refelems = findreferencingelements(deletablenodes, root, excludeelements=deletableelements)
        sharednodes += [i for i in deletablenodes if i in refelems.keys()]
        deletablenodes = [i for i in deletablenodes if i not in refelems.keys()]
        
        # exclude the node if referenced in a Nset
        for nsetnode in root.query("** > Nset"):
            if (nsetnode not in sets):
                # remove all nodes in nodesets
                cross_section = np.intersect1d(nsetnode.toarray(), deletablenodes)
                sharednodes += [i for i in deletablenodes if i in cross_section]
                deletablenodes = [i for i in deletablenodes if i not in cross_section]
                if (len(cross_section) > 0 and log):
                    print("- shares {:d} nodes with nset {:s}".format(len(cross_section), nsetnode.header.getproperty("nset")))
        if (log):
            print("Deleting nodes: {:d} unique nodes, {:d} nodes were shared with other elements".format(len(deletablenodes), nnodes - len(deletablenodes)))
    elif log:
        print("Deleting nodes: {:d} nodes".format(nnodes))
    
    sharednodes = unique(sharednodes)
    sharedelements = unique(sharedelements)
    if log:
        if (deletablenodes):
            print("*Nset, nset=DELETABLE_NODES, instance=PART-1-1")
            span = 16
            print("\n".join([" "+ ", ".join(map(str, deletablenodes[i:i+span])) for i in range(0, len(deletablenodes), span)]))
        if (sharednodes):
            print("*Nset, nset=SHARED_NODES, instance=PART-1-1")
            span = 16
            print("\n".join([" "+ ", ".join(map(str, sharednodes[i:i+span])) for i in range(0, len(sharednodes), span)]))        
        if (deletableelements):
            print("*Elset, elset=DELETABLE_ELEMENTS, instance=PART-1-1")
            span = 16
            print("\n".join([" "+ ", ".join(map(str, deletableelements[i:i+span])) for i in range(0, len(deletableelements), span)]))
        if (sharedelements):
            print("*Elset, elset=SHARED_ELEMENTS, instance=PART-1-1")
            span = 16
            print("\n".join([" "+ ", ".join(map(str, sharedelements[i:i+span])) for i in range(0, len(sharedelements), span)]))
        
    if (dodelete):
        # delete nodes
        node = next(root.query("Part > Node"))
        newcontent = []
        for line in node.getcontent():
            n = infernumber(line.split(",", 1)[0])
            if (n not in deletablenodes):
                newcontent += [line]
        node.content = newcontent

        # delete elements
        for elemnode in root.query("** > Element"):
            newcontent = []
            for line in elemnode.getcontent():
                el = infernumber(line.split(",", 1)[0])
                if (el not in deletableelements):
                    newcontent += [line]
            elemnode.content = newcontent
        
        # delete elsets
        for iset in sets:
            iset.getparent().getcontent().remove(iset)
            # Delete solid sections referencing elset 
            if (isinstance(iset, BlockReaderElset)):
                for solsec in root.query("** > Solid Section[elset="+iset.getheader().getproperty("elset")+"]", regex=False):
                    sec = solsec.getparent()
                    sec.getparent().getcontent().remove(sec)
            
    else:
        return deletableelements, deletablenodes