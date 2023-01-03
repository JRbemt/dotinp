from copy import deepcopy
import re 
import os
from enum import Enum
from io import StringIO
import numpy as np
import pandas as pd 
import sys
from collections import OrderedDict
import itertools, operator

MISSING_READER_ALERT = [None]
LOG_LEVEL = 1
REGEX_ENABLER_PREFIX = "ø"

# TODO:
# x allow semantic tree to be converted to simple block e.g. ([Controls, Material > User Material] etc.
# - Support comments 
# - extend parameteriation
# - behaviour for joining line ending in comma with nextline
# - Root header
# Done:
# - remove children and keep linenumbering intact



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

import annotations



class ReaderExitCode(Enum):
    CONTINUE = 0
    DONE = 1
    REJECT = 2
    ERROR = 3
    ERROR_NO_EOL_COMMA_ALLOWED = 4  # TODO
    
def infernumber(s, explicit=False):
    """
     Try to cast a string to a number (float/int)
     
     Parameters
     ----------
     s : string
        string to be be cast to number
     explicit : boolean, optional
         DESCRIPTION. The default is False.
     
     
     Returns
     -------
     float, int, or string
         Number best representing the string, 
         or string if it cannot be cast.
     
     """
    try:
        a = float(s)
        if (explicit and "." in s):
            # keep float if declared as float
            return a
        # downcast to int if no information is lost    
        return int(a) if (a == int(a)) else a
    except ValueError:
        return s
        
def findblockbyname(stck, name, regex = False):
    """
    Find INode by its name 

    Parameters
    ----------
    stck : list of INodes (or parent INode)
        ...
    name : string
        name of desired INode. The default is None.
    regex : boolean, optional
        Use regex. The default is False.

    Yields
    ------
    i : INode
        INode with matching name.

    """
    if isinstance(stck, INode):
        stck = stck.getchildren()
    for i in stck:
        if isinstance(i, INode) and (i.name == name if not regex else re.match(i.name, name)):
            yield i

def parseheader(line):
    """
    Parse name and proprties from header line
    
    e.g.
        *Soils, consolidation, end=PERIOD, utol=5.
    becomes:
        name = Soils,
        properties = {
            "consolidation": None,
            "end": "PERIOD",
            "utol": 5
        }


    Parameters
    ----------
    line : string
        line to be parsed.

    Returns
    -------
    name : string
        name of header.
    properties : OrderedDict
        properties listed in header.

    """
    segments = line.split(",")
    name =  segments[0]
    name = name.lstrip("* ")
    properties = OrderedDict()
    for i in segments[1:]:
        if ("=" in i):
            k, v = i.split("=")
            v = v.strip()
            properties[k.strip()] = infernumber(v)
        else:
            properties[i.strip()] = None
    return name, properties

def matchdict2str(dic, attrs, regex = True):
    """
    Match a dictionary to a template string
    
    e.g. 
        "consolidation,end=PERIOD"
        "consolidation,end=P.*"         (with regex)
        "consolidation,1=PERIOD"
    all match:
        {
            "consolidation": None,
            "end": "PERIOD",
            "utol": 5
        }
        

    Parameters
    ----------
    dic : dict
        ..
    attr : string
       template string used as matcher, with comma seperated attributes.
    regex : boolean, optional
        Use regex. The default is True.

    Returns
    -------
    bool
        True if matches.

    """
    for kv in attrs.split(","):
        if "=" in kv:
            k, v = kv.split("=")
            chead_val = None
            if k in dic.keys():
                chead_val = dic[k]
            elif (isinstance(dic, OrderedDict) and k.isnumeric()):
                chead_val = list(dic.values())[int(k)]
            else:
                return False
            if (chead_val is not None):
                if (not isinstance(chead_val, str)):
                    if (chead_val != infernumber(v)):
                        return False
                else:
                    regexlocal = regex 
                    if (v.startswith(REGEX_ENABLER_PREFIX)):
                        v = v.lstrip(REGEX_ENABLER_PREFIX)
                        regexlocal = True
                    if (regexlocal):
                        if (re.search(v, chead_val) == None):
                            return False
                    elif (v != chead_val):
                        return False
        
        elif (kv not in dic.keys()):
            return False
    return True

def matchcontent(content, match, regex = True):
    if (isinstance(content, BlockReaderBase)):
        content = content.getcontent()
    
    if regex:
        for i in content:
            if (isinstance(i, str)):
                if (re.search(match, i) != None):
                    return True
    else:
        for i in content:
            if (isinstance(i, str)):
                if (i == match):
                    return True
    return False
    
class ParameterizedLine(object):
    
    def __init__(self, line, name):
        """
        Line with comma seperated properties, stored as a name and OrderedDict

        Parameters
        ----------
        line : string
            Original line.
        name : string
            Name of the line.
        """
        self.name = name
        self.line = line
        self.properties = OrderedDict()
    
    @classmethod
    def fromheader(cls, line):
        """
        Create instance from a header line (.inp file)
        
        e.g.
            *Step, name = Step-1, nlgeom=YES, amplitude=RAMP, inc=1000

        Parameters
        ----------
        cls : TYPE
            DESCRIPTION.
        line : string
            The line.

        Returns
        -------
        paraml : ParameterizedLine
            Instance.

        """
        prs = parseheader(line)
        paraml = cls(line, prs[0])
        paraml.properties = prs[1]
        return paraml
    
    def getline(self):
        return self.line
    
    def getproperty(self, key):
        return self.properties[key]
        
    def __str__(self):
        return "{:s} {:s}".format(
            self.name, 
            "{"+", ".join([str(k)+": "+str(v) for k,v in self.properties.items()]) + "}"
        )
    
    def __repr__(self):
        return self.getline()

class INode(object):
    """
        INode object, has a header and can store content in order.
        Content can include other INode objects, therefore it offers
        an interface to create and utilize an object Tree.

    """
    def __init__(self, name, parent = None):
        """

        Parameters
        ----------
        name : string
            name of the node.
        parent : INode, optional
            Parent node. The default is None.


        """
        self.name = name
        self.content = []
        self._parent = parent 
        self.header = None
    
    def findchildrenbyname(self, name, regex=False):
        # TODO: debug should be yield?
        yield from findblockbyname(self.getcontent(), name, regex)
       
    def getheader(self):
        return self.header
       
    def getcontent(self):
        return self.content
        
    def getchildren(self):
        for line in self.getcontent():
            if isinstance(line, INode):
                yield line
    
    def getparent(self):
        return self._parent
        
    def hasparent(self):
        return self.getparent() != None
    
    def getroot(self):
        if (self.hasparent()):
            return list(self.upstreamhierarchy())[-1]
        else:
            return self
    
    def upstreamhierarchy(self):
        """
        Stream parents untill root is reached

        Yields
        ------
        _p : INode
            parent.

        """
        _p = self.getparent()
        while _p != None:
            yield _p 
            _p = _p.getparent()
               
    def _setparent(self, parent):
        self._parent = parent
        return self   
    
    def getname(self,):
        """
        Return name

        Returns
        ------
        string
            name

        """
        return self.name
    
    def getid(self,):
        """
        Return a more unique short name

        Returns
        ------
        string
            id

        """
        return self.name
    
    def flattencontent(self):
        """
        Yield all content and children (and their children recursively)
        
        Yields
        ------
        INode, string or any other dtype
            Child (content).
        """
        if (isinstance(self.getheader(), str)):
            yield self.getheader()
        else:
            yield repr(self.getheader())
        
        for i in self.getcontent():
            if isinstance(i, INode):
                yield from i.flattencontent()
            else:
                yield i
    
    def flatten(self,):
        """
            Flatten all children (and their children recursively)
            
            Yields
            ------
            INode, string or any other dtype
                Child (content).
        """
        for i in self.getchildren():
            yield i
            yield from i.flatten()

    def query(self, query, regex = False):
        """
        Query the INode tree 
        
        Attributes (in the header):
            parent[key=value]   # test for value (allows regexs)
                                # regex can be enabled per value if first character of value is REGEX_ENABLER_PREFIX
            parent[key]         # test for presence
        Content:
            parent(content)     # match parent if content matches 
                                # regex can be enabled if first character is REGEX_ENABLER_PREFIX
        Keyords:
            >           : child selector
            |           : match multiple nodes
            *           : match all children
            **          : match all children and their children and so on
            ..          : move to parent
            root        : move to root
            
        Example, query solid section:
        
        Root
        *Part {name: PART-1}                                                                                  
        *| └-Section: Section-11-F1 {}                                                                         
        *| | └-Solid Section {elset: F1, material: FACETS}                                                          
        *| └-Section: Section-12-F2 {}                                                                           
        *| | └-Solid Section {elset: F2, material: FACETS}                                                      
        *| └-Section: Section-13-F3 {}
        *| ...
        
        Query:
            Part > Section > Solid Section[elset=F\d]
        Or:
            Part > Section > Solid Section[0=F\d]
            
        Yields
        ------
        INode
            Queried child
        """
        if ">" in query:
            parentname, childname = query.split(">", 1)
            for parent in self.query(parentname.strip(), regex = regex):
                yield from parent.query(childname.strip(), regex = regex)
        elif "|" in query:
            # match multiple children
            for term in query.split("|"):
                yield from self.query(term.strip(), regex = regex)
        elif "[" in query:
            # filter for attributes
            name = query[:query.find("[")] + query[query.find("]")+1:]
            attr = query[query.find("[")+1:query.find("]")]
            yield from filter(lambda x: matchdict2str(x.getheader().properties, attr, regex = regex), self.query(name, regex = regex))
        elif "(" in query:
            # match content
            name = query[:query.find("(")] + query[query.find(")")+1:]
            match = query[query.find("(")+1:query.find(")")]
            regexlocal = regex
            if (match.startswith(REGEX_ENABLER_PREFIX)):
                match = match.lstrip(REGEX_ENABLER_PREFIX)
                regexlocal = True
            yield from filter(lambda x: matchcontent(x, match, regex = regexlocal), self.query(name, regex = regex))
        elif (query.strip() == "*"):
            # match all children
            yield from self.getchildren()
        elif (query.strip() == "**"):
            # match all children and their children (flatten)
            yield from self.flatten()
        elif (query.strip() == ".."):
            # move to parent
            yield self.getparent()
        elif (query.strip() == "root"):
            # move to root
            yield self.getroot()
        else:
            # return child
            yield from self.findchildrenbyname(query, regex = regex)
    
    def printchildren(self, out = print, level = 0):
        """
        Print this node and its childrend as a Tree

        Parameters
        ----------
        level : int, optional
            level to start. The default is 0.

        Returns
        -------
        None.

        """
        prefix = ""
        if level == 0:
            pass
        elif level == 1:
            prefix = "*"
        else:
            prefix = "*" + "| "*(level-1)+"└-"
        

        trimspacer = True
        formatplain = not trimspacer
        selfstr = str(self)
        if (trimspacer and len(selfstr) > 10):
            reps = [selfstr[i] == selfstr[i+1] for i in range(len(selfstr)-1)]
            # find longest space (repeating characters)
            if (True in reps):
                seq = max((list(y) for (x,y) in itertools.groupby((enumerate(reps)),operator.itemgetter(1)) if x == True), key=len)
                size = seq[-1][0] - seq[0][0]
                rem = min(len(prefix), size-1)
                out(prefix + selfstr[:seq[0][0]] + selfstr[seq[0][0]+rem:])
            else:
                formatplain = True
        else:
            formatplain = True
       
        if (formatplain):
            out(prefix + selfstr)
        
        for i in self.getchildren():
            i.printchildren(out=out, level=level+1)
    
    def printparents(self, out = print):
        parents = [self] + list(self.upstreamhierarchy())
        for i, par in enumerate(parents[::-1]):
            if (par != None):
                if (i == 0):
                    out(str(par))
                elif (i == 1):
                    out("*" + str(par))
                else:
                    out("*" + "| "*(i-1)+"└-" + str(par))
      
    def __len__(self):
        size = 0 if self.getheader() == None else 1
        for _x in self.getcontent():
            if isinstance(_x, str):
                size += 1
            else:
                size += len(_x)
        return size
    
    def __str__(self):
        if (self.getheader() is not None):
            return "{:<120s} lines {:s}".format(str(self.getheader()).rstrip("\n"), 
                    str(self.getlinenumberrange()))
        else:
            return "{:<120s} ({:s})".format(self.getname(), "MOCK")
       
    def __repr__(self):
        strarr = []
        content = [self.getheader()] + self.getcontent() if self.getheader() != None else self.getcontent()
        for _x in content:
            if isinstance(_x, str):
                strarr += [_x.rstrip("\n")]
            else:
                strarr += [repr(_x)]
        return "\n".join(strarr)


""""     
class IBlockReader(object):
    def __init__(self):
        self._isreading = False
        self.startlinenumber = None
    
    def matchheader(line):
        return False
    
    def startreading(self, startlinenumber = 0):
        self._isreading = True
        self.startlinenumber = startlinenumber
    
    def read(self, line, nextreader = None):
        return ReaderExitCode.ERROR
       
    def stopreading(self):
        self._isreading = False
        
    def isreading(self):
        return self._isreading
    
    def getheader(self):
        return self.header
        
    def getstartlinenumber(self):
        return self.getstartlinenumber
"""
class BlockReaderBase(INode):
    """
        An implementation of INode offering the reading of lines of text and 
        store them as other BlockReaderBase instances (functional block) or as 
        a string.
        Specifically designed for Abaqus .inp files
    """
    def __init__(self, name, parent = None, 
                 acceptchildren = True, acceptunimplementedchildren = True, 
                 childreaderresolver = None):
        """
        
        """
        super().__init__(name, parent)
        self.childreaderresolver = childreaderresolver
        
        self.startlinenumber = None     # starting line of this block corresponding to line in file
        self._nlines = 0                # counter for the amount of lines read
        self._isreading = False         # current state
        self._activechildreader = None  # active child reader to which lines are delegated
        
        # Behaviour
        self.acceptchildren = acceptchildren                            # accept childreader
        self.acceptunimplementedchildren = acceptunimplementedchildren  # accept functional block, without corresponding childreader (as text)
        self.preferchildoversibling = True       # if true and both a next horizontalreader and a next child reader present 
                                                 # choose the childreader
        self.takesiblingpreference = True        # useful when same reader can both occur as a child or sibling
        #self.allowcommaEOL = True      # TODO
        self.stripEOL = True
               
    def matchheader(self, line):
        """
         Looks at the header of the next coming functiona block and 
         returns true if this class can handle that block

         Parameters
         ----------
         line : string
            A line of text (which is a potential header of an upcoming functional block)
         
         Returns
         -------
         boolean
            True if this class can handle the upcoming functional block
         
        """
        return False
        
    def startreading(self, startlinenumber = -1):
        """
         Prepare the reader for reading

         Parameters
         ----------
         startlinenumber : int
            Where in the file this line can be found
         
         Returns
         -------
         None
            
        """
        if (len(self.getcontent()) > 0):
            raise ValueError("[{:^20s}] Cannot start reading when block has pre-existing content".format(self.getid()))
        self._isreading = True
        self.startlinenumber = startlinenumber
        self.content = []
          
    def read(self, line, nextsiblingeader = None):
        """
         Read the line (or header) which is part of this functional block

         Parameters
         ----------
         line : string
            A line of text
         nextchildreader : BlockReaderBase
            Another reader (sibling relationship) which also matches the line of text as a header
            and can thus potentially take-over parsing
            
         Returns
         -------
         enum ReaderExitCode
            CONTINUE    -   ready for parsing next line of text
            DONE        -   finished parsing this functional block
            REJECT      -   finished parsing this functional block and the current line
                            is not a part of it
         
        """
        if not self.isreading():
            raise ValueError("[{:^20s}] Start reader first".format(self.getid()))
        if self.stripEOL:
            line = line.rstrip("\n")
        if LOG_LEVEL >= 2:
            print("[{:^20s}] received line ({:d}): \"{:s}\" and nextsiblingeader: {:s}".format(self.getid(), self.getendlinenumber(), line, str(nextsiblingeader)))
        
        if self.getheader() is None:
            self.header = self.parameterizeheader(line)
            if LOG_LEVEL >= 2:
                print("[{:^20s}] set header".format(self.getid()))
        else:
            if self.doterminate(line, nextsiblingeader):
                if LOG_LEVEL >= 2:
                    print("[{:^20s}] terminated".format(self.getid()))
                self.stopreading()
                return ReaderExitCode.REJECT
                
            nextchildreader = None
            # Child reader
            if (self.isfunctionalblock(line)):
                nextchildreader = self._resolvechildreader(line)
                    
                # No active child reader yet
                if (not self._hasactivechildreader()):
                    if (nextchildreader is not None):
                        self._activatechildreader(nextchildreader)
            
            if (not self._hasactivechildreader()):
                # Read normal line (or property)
                self.getcontent().append(self.parameterize(line))
                if LOG_LEVEL >= 2:
                    print("[{:^20s}] appended content".format(self.getid())) 
            else:
                # Delegate to child reader
                rsp = self._activechildreader.read(line, nextchildreader)
                if (rsp in [ReaderExitCode.DONE, ReaderExitCode.REJECT]):
                    self._stopactivechildreader()
                    
                    if (rsp == ReaderExitCode.REJECT):
                        if (nextchildreader is not None):
                            # This block can be ommited
                            self._activatechildreader(nextchildreader)
                        
                        if LOG_LEVEL >= 2:
                            print("[{:^20s}] redo".format(self.getid()))
                        return self.read(line, nextsiblingeader)
        self._nlines += 1   
        return ReaderExitCode.CONTINUE
    
    def _resolvechildreader(self, line):
        if (self.acceptchildren and self.getchildreaderresolver() is not None):
            return deepcopy(self.getchildreaderresolver()(line))
        else:
            return None
    
    def _stopactivechildreader(self):
        self._activechildreader.stopreading()
        self.getcontent().append(self._activechildreader)
        self._activechildreader = None
    
    def _activatechildreader(self, nextchildreader):
        self._activechildreader = nextchildreader
        self._activechildreader.startreading(self.getendlinenumber())   
        self._activechildreader._setparent(self)
    
    def _hasactivechildreader(self):
        """
         Returns
         -------
         boolean 
            True if a childreader is active
         
        """
        return self._activechildreader is not None
    
    def iscomment(self, line):
        return line.lstrip().startswith("**")
    
    def isfunctionalblock(self, line):
        """
         Looks at the header of the next coming functiona block and 
         returns true if this class can handle that block

         Parameters
         ----------
         line : string
            A line of text (which is a potential header of an upcoming functional block)
         
         Returns
         -------
         boolean
            True if this class can handle the upcoming functional block
         
        """
        # TODO: should exclude comments (**) as soon as they are supported 
        return line.lstrip().startswith("*")
    
    def stopreading(self):
        """
         Stop the reader

         Parameters
         ----------
         line : string
            A line of text (which is a potential header of an upcoming functional block)
         
         Returns
         -------
         boolean
            True if this class can handle the upcoming functional block
         
        """
        if (self._activechildreader != None):
            self._stopactivechildreader()
        self._isreading = False
        
    def doterminate(self, line, nextsiblingeader):
        """
         Determine if this reader can handle the line,
         or whether a potential next reader should take-over

         Parameters
         ----------
         line : string
            A line of text (which is a potential header of an upcoming functional block)
         nextreader: BlockReaderBase
            Another reader on the same level (sibling), which wants to take-over parsing
         
         Returns
         -------
         boolean
            True if this reader should stop
         
        """
        hasnextchildreader = self._resolvechildreader(line) is not None
        if (nextsiblingeader is not None):
            if (self.isfunctionalblock(line)):
                # Dismiss next reader if a child can handle it
                if (hasnextchildreader):
                    # refuse next sibling reader if:
                    # 1. current reader insists on preference for childreader over siblingreader
                    # 2. next siblingreader does not want preference
                    if (self.preferchildoversibling \
                            or not nextsiblingeader.takesiblingpreference): 
                        return False
                       
                # next block
            return True
        elif (hasnextchildreader):
            return False
        else:
            if (self.iscomment(line)):
                return False
            elif (self.isfunctionalblock(line)):
                # child block without corresponding reader class
                # Notify missing behaviour
                self.__notifymissingreader(line)
                return not self.acceptunimplementedchildren
        return False
    
    def isreading(self):
        """
         Returns
         -------
         boolean
            True if this reader is currently reading
         
        """
        return self._isreading 
    
    def setchildreaderresolver(self, prop):
        self.childreaderresolver = prop
        return self
    
    def getchildreaderresolver(self):
        """
         Get the childreader resolver.
        
         Returns
         -------
         lambda
            A function taking a string as argument (line) 
            and returning an BlockReaderBase or None
         
        """
        return self.childreaderresolver
    
    def getstartlinenumber(self):
        """
         Returns
         -------
         int
            corresponding to linenumber where this functional block starts in the file
         
        """
        if (self.startlinenumber == None):
            raise ValueError("Start line number was never defined")
        return self.startlinenumber
        
    def getlinenumberrange(self):
        """
         Returns
         -------
         tuple : (int, int)
            (startlinenumber, endlinenumber)
         
        """
        return (self.getstartlinenumber(), self.getendlinenumber() - 1)       
        
    def getendlinenumber(self):
        """
         Returns
         -------
         int
            endlinenumber
         
        """
        return self.getstartlinenumber() + len(self)
        
    def parameterizeheader(self, line):
        """
            Option to perameterize a header into an object
            e.g. 
                *Element type=S4R
            becomes:
                {
                 "type": "S4R",
                }
        """
        return ParameterizedLine.fromheader(line)
    
    def parameterize(self, line):
        """
            Option to perameterize a property of a block into an object
            e.g. 
                0.1, 60, 0.0001, 60
            becomes:
                {
                 "initial": 0.1,
                 "period": 60,
                 "min": 0.0001,
                 "max": 60
                }
        """
        return line
             
    def numberedflattencontent(self):
        """
         
         TODO:
            - test synergy with *INCLUDE (maybe get startlinenumber of block itself?)
        
         Yields
         -------
         tuple : (int, string)
            (linenumber, content)
         
        """
        i = 0
        for l in self.flattencontent():
            yield (self.getstartlinenumber()+ i, l)
            i += 1
    
    def updatestartlinenumber(self, number):
        """
         When content is removed, update the linenumbers (of this block and its children)
         to be continuous again
            
            
         Parameters
         ----------
         number : int
            New Start line number
         nextreader: BlockReaderBase
            Another reader on the same level (sibling), which wants to take-over parsing
         
         Returns
         -------
         boolean
            True if this reader should stop
         
        """
        self.startlinenumber = number
        children = {i.getheader().line: i for i in self.getchildren()}
        for n, l in self.numberedflattencontent():
            if (l in children.keys()):
                children[l].updatestartlinenumber(n) 
    
    def __notifymissingreader(self, line):
        if (line.lstrip().startswith("**")):
            pass
        elif(self.isfunctionalblock(line)):
            readername = line.lstrip(" * ")
            if ("," in readername):
                readername = readername.split(",", 1)[0]
            global MISSING_READER_ALERT
            parentstr = [i.getname() for i in self.upstreamhierarchy()][::-1]
            parentstr = " > ".join(parentstr + [self.getname(), readername])
            if (parentstr.lower() not in MISSING_READER_ALERT):
                MISSING_READER_ALERT += [parentstr.lower()]
                print("NOTE: No explicit reader class defined for {:<40s} at line {:d}".format(parentstr, self.getendlinenumber()))
        
    def __len__(self):
        if (self.isreading() and self._activechildreader != None):
            return super().__len__() + len(self._activechildreader)
        else:
            return super().__len__()

#--------------------------------------------------------------
#
# Functional blocks (roots) 
#
#--------------------------------------------------------------
 
 
@annotations.deprecated()  
class RootReaderOld(INode):
    # TODO: file header support
    def __init__(self, chilreaderresolver):
        super().__init__("Root")
        self.childreaderresolver = chilreaderresolver
        self._nlines = 0
        self._originfile = None
        self.cwd = None             # working directory
    
    def parse(self, iterable): 
        if isinstance(iterable, str):
            iterable = iter(iterable.split("\n"))
        
        activereader = None
        linenumber = 0
        redolines = []
        while True:
            line = None
            if len(redolines) > 0:
                line = redolines.pop(0)
                linenumber -= 1
            else:
                line = next(iterable, None)
            
            # TODO support comma at EOL
            if line == None:
                if (activereader):
                    activereader.stopreading()
                    self.getcontent().append(activereader)
                break
            
            nextreader = deepcopy(self.getchilreaderresolver()(line))   
            
            # no active reader yet
            if (activereader is None and nextreader is not None):
                activereader = nextreader
                activereader.startreading(linenumber)
                activereader._setparent(self)
            
            if activereader is not None:
                rsp = activereader.read(line, nextreader)
                if (rsp in [ReaderExitCode.DONE, ReaderExitCode.REJECT]):
                    # stop active reader
                    activereader.stopreading()
                    self.getcontent().append(activereader)
                    activereader = None
                    
                    if (rsp == ReaderExitCode.REJECT):
                        redolines.append(line)
                        # follow up with next reader
                        # this block can be omitted
                        if nextreader is not None:
                            activereader = nextreader
                            activereader.startreading(linenumber)
                            activereader._setparent(self)
            else:
                self.getcontent().append(line)
            linenumber += 1
        self._nlines += linenumber
        return self
    
    def parseinputfile(self, filepath): 
        self._originfile = filepath  
        self.cwd = os.path.dirname(os.path.realpath(filepath))
        with open(filepath, 'r') as fin_handle:
            self.parse(fin_handle)
        return self
    
    def getchilreaderresolver(self):
        return self.childreaderresolver
    
    def __str__(self):
        return "Root"        

class RootReader(BlockReaderBase):
    def __init__(self, childreaderresolver):
        super().__init__("Root", childreaderresolver = childreaderresolver, 
                            acceptchildren = True)
        self.acceptunimplementedchildren = True
        self._originfile = None
        self.cwd = None             # working directory
    
    def parse(self, iterable): 
        if isinstance(iterable, str):
            iterable = iter(iterable.split("\n"))
        
        if (not self.acceptchildren):
            raise ValueError("Root reader must accept children")
        
        # TODO: ROOT file header support
        self.startreading(0)
        for line in iterable:
            self.read(line, None)
        self.stopreading()
        return self
    
    def parseinputfile(self, filepath): 
        self._originfile = filepath  
        self.cwd = os.path.dirname(os.path.realpath(filepath))
        with open(filepath, 'r') as fin_handle:
            self.parse(fin_handle)
        return self           
    
    def getcwd(self):
        """
        Returns
        -------
        string
            current working directory
        """
        return self.cwd
    
    def realignlinenumbers(self):
        if (self.getparent() != None):
            self.getroot().realignlinenumbers()
        else:
            self.updatestartlinenumber(0)
    
    def savetofile(self, filename):
        """
         Write the data tree to a file
        """
  
        filepath = None if any(dirslash in filename for dirslash in ["\\", "/"]) else self.getcwd()
        filename = filename if filename.rstrip().endswith(".inp") else filename + ".inp"
        fullpath = os.path.join(filepath, filename)
        with open(fullpath, "w") as outf:
            outf.write(repr(self))
        
    def __str__(self):
        return self.getname()        
               
class IncludeReader(RootReader):
    def __init__(self, childreaderresolver = None, inline = False):
        super().__init__(childreaderresolver)
        self.name = "Include"
        self.inline = inline
        self.takesiblingpreference = False

    def matchheader(self, line):
        return not line.lstrip().startswith("**") \
                and line.lstrip("* ").lower().startswith("include") 
    
    def read(self, line, nextsiblingeader = None):
        if self.getheader() == None:
            if LOG_LEVEL >=1:
                print("INCLUDE", line)
            self.header = ParameterizedLine.fromheader(line)
            infile = self.getheader().getproperty("input")
            if (not os.path.isabs(infile)):
                cwd = self.getroot().getcwd()
                if (cwd == None):
                    cwd = os.getcwd()
                infile = os.path.join(cwd, infile)
            
            self.parseinputfile(infile)
            return ReaderExitCode.DONE
        else:
            return super().read(line, nextsiblingreader)
    
    def setinline(self, inline):
        """
            Treat the block as just the original Include line if false,
            else pretend the content of the included file is there inplace
        """
        self.inline = inline
        return self
    
    def getchildreaderresolver(self):
        if super().getchildreaderresolver() != None:
            super().getchildreaderresolver()
        else:
            return self.getparent().getchildreaderresolver()
    
    def savetofile(self):
        # TODO: support for include modifications
        raise ValueError("Not yet implemented")
    
    def __len__(self):
        # TODO: test with #numberedflattencontent
        if (self.inline):
            return super().__len__()
        else:
            return 1
    
    def __repr__(self):
        if (self.inline):
            # make comment instead
            strarr = ["*" + self.getheader().getline()]
            for _x in self.getcontent():
                if isinstance(_x, str):
                    strarr += [_x.rstrip("\n")]
                else:
                    strarr += [repr(_x)]
            return "\n".join(strarr)
        else:
            if (self.getheader() is not None):
                return self.getheader().getline()
            else:
                return self.__str__()

#--------------------------------------------------------------
#
# Functional blocks
#
#--------------------------------------------------------------

class BlockReaderElement(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Element", childreaderresolver = childreaderresolver,
                        acceptchildren = True, acceptunimplementedchildren = False)
        
    def matchheader(self, line):
        return not self.iscomment(line) and \
               line.strip("* ").startswith("Element,") 
    
    def getid(self):
        if (self.getheader() != None):
            return self.name + ":"+self.getheader().getproperty("type")
        else:
            return super().getid()
    
    def gettype(self):
        return self.getheader().getproperty("type")
        
    def todataframe(self):
        csvStringIO2 = StringIO("\n".join(self.getcontent()).replace(" ", ""))
        header = ["element"] + ["n{:d}".format(_i) for _i in range(1, len(self.getcontent()[0].split(",")))]
        df = pd.read_csv(csvStringIO2, sep=",", header=None, names=header, index_col=0)
        csvStringIO2.close()
        return df
        
class BlockReaderNode(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Node", childreaderresolver = childreaderresolver, 
                        acceptchildren = True, acceptunimplementedchildren = False)
        
    def matchheader(self, line):
        namepart = line.split(",")[0]
        return not self.iscomment(namepart) and \
               namepart.rstrip(" \n").endswith("Node")
                
    def todataframe(self):
        csvStringIO2 = StringIO("\n".join(self.getcontent()).replace(" ", ""))
        header = ["node", "x", "y", "z"]
        df = pd.read_csv(csvStringIO2, sep=",", header=None, names=header, index_col=0)
        csvStringIO2.close()
        return df
    
class BlockReaderNset(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Nset", childreaderresolver = childreaderresolver,
                        acceptchildren = True, acceptunimplementedchildren = False)
        
    def matchheader(self, line):
        return not self.iscomment(line) and \
               line.strip("* ").startswith("Nset,")   
    
    def getid(self):
        if (self.getheader() != None):
            return self.name + ":"+self.getheader().getproperty("nset")
        else:
            return super().getid()

    def toarray(self):
        csvStringIO = StringIO(",".join(self.getcontent()).replace("\n", "").replace(" ", ""))
        arr = pd.read_csv(csvStringIO, sep=",", header=None).T.squeeze().values
        csvStringIO.close()
        return arr
        
    def linkednodes(self, node):
        if (node == Node):
            node = self.query("root > Part > Node")
        
        nodes = node.todataframe()
        return nodes.loc[self.toarray(),:]

class BlockReaderElset(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Elset", childreaderresolver = childreaderresolver,
                acceptchildren = True, acceptunimplementedchildren = False)
        
    def matchheader(self, line):
        return not self.iscomment(line) and \
                line.strip("* ").startswith("Elset,")
    def getid(self):
        if (self.getheader() != None):
            return self.name + ":"+self.getheader().getproperty("elset")
        else:
            return super().getid()
            
    def toarray(self):
        csvStringIO = StringIO(",".join(self.getcontent()).replace("\n", "").replace(" ", ""))
        arr = pd.read_csv(csvStringIO, sep=",", header=None).T.squeeze().values
        csvStringIO.close()
        return arr
     
    def linkedelements(self, elements = None):
        if (elements == None):
            elements = self.query("root > Part > Element")
        arr = self.toarray()
        for i in elements:
            elem_df = i.todataframe()
            xs = [_el for _el in arr if _el in elem_df.index]
            if (xs):
                yield (elem_df.loc[xs,:], i)    
      
class BlockReaderSurface(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Surface", childreaderresolver = childreaderresolver,
                acceptchildren = True, acceptunimplementedchildren = False)
        
    def matchheader(self, line):
        line = line.lstrip()
        return line.startswith("*") and line[1:].startswith("Surface,")    
        
class BlockReaderDistribution(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Distribution", childreaderresolver = childreaderresolver,
                        acceptchildren = True, acceptunimplementedchildren = False)
        
    def matchheader(self, line):
         return not self.iscomment(line) and \
                line.strip("* ").startswith("Distribution,")
        
class BlockReaderMaterial(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Material", childreaderresolver = childreaderresolver,
                        acceptchildren = True, acceptunimplementedchildren = True)
        
    def matchheader(self, line):
        line = line.lstrip()
        return line.startswith("*") and line[1:].startswith("Material,")  

class SectionChildBase(BlockReaderBase):
    def __init__(self, name, acceptchildren = False):
        super().__init__(name = name, acceptchildren = acceptchildren)
        
    def matchheader(self, line):
        return not self.iscomment(line) and \
                    line.lstrip("* ").startswith(self.getname()+",")
        
    def linkedelset(self, elsets = None):
        if (elsets == None):
            elsets = self.query(" .. > .. > Elset")
        for _e in elsets:
            if (self.getheader().getproperty("elset") == _e.getheader().getproperty("elset")):
                return _e
    
    def linkedmaterial(self, materials = None):
        if (materials == None):
            materials = self.query("root > Material")
        for _m in materials:
            if (self.getheader().getproperty("material") == _m.getheader().getproperty("name")):
                return _m
    
    def linkedorientation(self, orientation = None):
        if (orientation == None):
            orientation = self.query(" .. > .. > Orientation")
        for _o in orientation:
            if (self.getheader().getproperty("orientation") == _o.getheader().getproperty("name")):
                return _o
            
class BeamSection(SectionChildBase):
    def __init__(self):
        super().__init__(name = "Beam Section", acceptchildren = False)

class SolidSection(SectionChildBase):
    def __init__(self):
        super().__init__(name = "Solid Section", acceptchildren = False)
    
class ShellSection(SectionChildBase):
    def __init__(self):
        super().__init__(name = "Shell Section", acceptchildren = False)
     
class BlockReaderSection(BlockReaderBase):
    """"
        TODO: **Section is just an auto-generated comment or a block??
    """
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Section", 
            acceptchildren = True, acceptunimplementedchildren = False, 
            childreaderresolver = childreaderresolver)        
        
    def matchheader(self, line):
        return line.lstrip("* ").startswith("Section:")
    
    def getid(self):
        if (self.getheader() != None):
            id = self.getheader().name[8:].lstrip()
            return id[:id.find(" ")]
        else:
            return super().getid()
        
class BlockReaderParameter(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Parameter", childreaderresolver = childreaderresolver,
                    acceptchildren = True, acceptunimplementedchildren = False)
        
    def matchheader(self, line):
        line = line.lstrip()
        return line.startswith("*") and line[1:].startswith("parameter")
        
class BlockReaderOrientation(BlockReaderBase):
    """
        http://130.149.89.49:2080/v6.11/books/key/default.htm?startat=ch15abk01.html#usb-kws-morientation
    """
    def __init__(self, childreaderresolver = None):
        super().__init__(name = "Orientation", childreaderresolver = childreaderresolver,
                        acceptchildren = True, acceptunimplementedchildren = False)
        
        self.definedorientation = None  # line 1
        self.rotation = None
        self.localdirections = []
        
    def matchheader(self, line):
        return not self.iscomment(line) and \
                line.strip("* ").startswith("Orientation")
        
    def parameterizeheader(self, line):
        #TODO: cls instantiator
        prs = parseheader(line) 
        header = self.OrientationHeader(line, prs[0])
        header.properties = prs[1]
        return header
    
    def getdefinedorientation(self):
        return self.definedorientation
        
    def getrotation(self):
        return self.rotation
    
    def getlocaldirections(self):
        return self.localdirections
    
    def parameterize(self, line):
        if (not line.lstrip().startswith("*")):
            if (self.getdefinedorientation() is None):
                if (self.getheader().getdefinition().lower() == "coordinates"):
                    aaabbbcc = list(line.strip("\n ").rstrip(".").split(","))
                    self.definedorientation = tuple(map(infernumber, aaabbbcc))
                    
                elif (self.getheader().getdefinition().lower() in ["nodes", "offset to nodes"]):
                    abc = list(line.strip("\n ").rstrip(".").split(","))
                    if len(abc) == 3:
                        abc[2] = abc[2] if abc[2] != "" else 1
                    else:
                        abc.append(1)
                    self.definedorientation = tuple(map(infernumber, abc))
                    
            elif (self.getrotation() is None):
                rot_ax, alpha = line.strip("\n ").rstrip(".").split(",")
                rot_ax = infernumber(rot_ax) if rot_ax.strip() != "" else 1
                alpha = infernumber(alpha) if alpha.strip() != "" else 0
                self.rotation = (rot_ax, alpha)
            
            elif(self.getheader().getlocaldirections() is not None \
                and (len(self.getlocaldirections()) <= self.getheader().getlocaldirections())):
                xyz =  line.strip("\n ").rstrip(".").split(",")
                self.localdirections.append(tuple(map(infernumber, xyz)))       
        # TODO: if full parameterizable the line does not necesarrily have to be stored as a string as well
        return line
     
    class OrientationHeader(ParameterizedLine):
        def __init__(self, line, name):
            super().__init__(line, name)
    
        def getlocaldirections(self):
            """
                int or None
            """
            return self.properties.get("local directions", None)    

        def getsystem(self):
            """
                rectangular, cyllindrical, spherical, z rectangular, user
            """
            return self.properties.get("system", "rectangular")
                
        def getdefinition(self):
            """
                coordinates, nodes, offset to nodes
            """
            return self.properties.get("definition", "coordinates")

class BlockReaderAssembly(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        self._terminatenextline = False
        super().__init__(name = "Assembly", 
                    acceptchildren = True, acceptunimplementedchildren = True,
                    childreaderresolver = childreaderresolver)
       
    def matchheader(self, line):
        return not self.iscomment(line) and \
                line.lstrip("* ").startswith("Assembly")
    
    def getid(self):
        if (self.getheader() != None and "name" in self.getheader().properties):
            return self.name + ":"+self.getheader().getproperty("name")
        else:
            return super().getid()
    
    def read(self, line, nextsiblingreader = None):
        if ("end assembly" in line.lower()):
            self.stopreading()
            self.getcontent().append(line)
            self._nlines += 1
            return ReaderExitCode.DONE
        else:
            super().read(line, nextsiblingeader)
    
    def doterminate(self, line, nextreader = None):
        # gready
        return False

class BlockReaderPart(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        self._terminatenextline = False
        super().__init__(name = "Part", 
                acceptchildren = True, acceptunimplementedchildren = True,
                childreaderresolver = childreaderresolver)
        
    def matchheader(self, line):
        return not self.iscomment(line) and \
                line.lstrip("* ").startswith("Part")
    
    def getid(self):
        if (self.getheader() != None and "name" in self.getheader().properties):
            return self.name + ":"+self.getheader().getproperty("name")
        else:
            return super().getid()
            
    def read(self, line, nextsiblingeader = None):
        if ("end part" in line.lower()):
            self.stopreading()
            self.getcontent().append(line)
            self._nlines += 1
            return ReaderExitCode.DONE
        else:
            super().read(line, nextsiblingeader)
    
    def doterminate(self, line, nextsiblingeader = None):
        # gready
        return False

class BlockReaderStep(BlockReaderBase):
    def __init__(self, childreaderresolver = None):
        self._terminatenextline = False
        super().__init__(name = "Step", 
                        acceptchildren = True, acceptunimplementedchildren = True,
                        childreaderresolver = childreaderresolver)
        
    def matchheader(self, line):
        return not self.iscomment(line) and \
                line.lstrip("* ").startswith("Step")
    
    def getid(self):
        if (self.getheader() != None and "name" in self.getheader().properties):
            return self.name + ":"+self.getheader().getproperty("name")
        else:
            return super().getid()
            
    def read(self, line, nextreader = None):
        if ("end step" in line.lower()):
            self.stopreading()
            self.getcontent().append(line)
            self._nlines += 1
            return ReaderExitCode.DONE
        else:
            super().read(line, nextreader)
    
    def doterminate(self, line, nextreader = None):
        # gready
        return False


def findreader(readers, line):
    for reader in readers:
        if reader.matchheader(line):
            return reader
    return None

def __FUSE_RESOLVERS(*args):
    def __fuse_resolvers_internal(x):
        for res in args:
            result = res(x)
            if (result is not None):
                return result
        return None
            
    return __fuse_resolvers_internal

def __DEFAULT_RESOLVER_BUILDER(readers):
    #print(list(map(lambda x: x.getname(),readers)))
    return lambda x: findreader(readers ,x)

__GENERIC_RESOLVER = __DEFAULT_RESOLVER_BUILDER([
                            IncludeReader()
                     ])
__PART_RESOLVER = __FUSE_RESOLVERS(
    __DEFAULT_RESOLVER_BUILDER([
        BlockReaderNode(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderElement(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderNset(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderElset(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderSurface(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderMaterial(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderDistribution(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderSection(childreaderresolver = __FUSE_RESOLVERS(__GENERIC_RESOLVER,
                                                                __DEFAULT_RESOLVER_BUILDER([
                                                                        SolidSection(),
                                                                        ShellSection(),
                                                                        BeamSection(),                                                             
                                                                    ])
                                                                )),
        BlockReaderParameter(childreaderresolver = __GENERIC_RESOLVER),
        BlockReaderOrientation(childreaderresolver = __GENERIC_RESOLVER),
    ]),
    __GENERIC_RESOLVER
)

__ASSEMBLY_RESOLVER = __PART_RESOLVER

DEFAULT_RESOLVER = __FUSE_RESOLVERS(
    __DEFAULT_RESOLVER_BUILDER([
        BlockReaderAssembly(childreaderresolver = __PART_RESOLVER),
        BlockReaderPart(childreaderresolver = __ASSEMBLY_RESOLVER),
        BlockReaderStep(childreaderresolver = __GENERIC_RESOLVER),
    ]),
    __PART_RESOLVER
)

def parseinputfile(infile, childreaderresolver = DEFAULT_RESOLVER):
    return RootReader(childreaderresolver).parseinputfile(infile)

if __name__ == "__main__":
    infile = os.path.join(codedir,'../v13/MUSC_HEALTHY.inp')
    #infile = os.path.join(codedir,'./TEST_TEMPLATES/SIMPLE_INCLUDE.txt')
    
    root = parseinputfile(infile)
    #print("\n".join(map(str, root.query("**"))))