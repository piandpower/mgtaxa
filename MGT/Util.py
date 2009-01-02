from types import *
import re
import string, os
from time import sleep
import time
from copy import copy, deepcopy
from cPickle import dump, load
from cStringIO import StringIO
import numpy
n = numpy
import numpy.random as nrnd
from tempfile import mkstemp
from textwrap import dedent
from collections import defaultdict as defdict

from MGT.Options import Struct
from MGT.Config import options, Options

from subprocess import Popen, call, PIPE

defineCalledProcessError = False
try:
    from subprocess import CalledProcessError
except ImportError:
    defineCalledProcessError = True

if defineCalledProcessError:

    class CalledProcessError(OSError):
        def __init__(self,returncode,*l,**kw):
            OSError.__init__(self,*l,**kw)
            self.returncode = returncode


from MGT.Bits.Unique import unique, uniquePick

def dumpObj(obj,fileName):
    out = openCompressed(fileName,'w')
    dump(obj,out,-1)
    out.close()
    
def loadObj(fileName):
    inp = openCompressed(fileName,'rb')
    ret = load(inp)
    inp.close()
    return ret

def allChr():
    """Return a string with all characters in C local [0-255]"""
    return ''.join([chr(i) for i in range(256)])

class objectDiskCacher:

    def __init__(self,factory,fileName,recreate=False):
        self.factory = factory
        self.fileName = fileName
        self.recreate = recreate
        
    def __call__(self,*l,**kw):
        if ( not os.path.isfile(self.fileName) ) or self.recreate:
            o = self.factory(*l,**kw)
            dumpObj(o,self.fileName)
        else:
            o = loadObj(self.fileName)
        return o

def run(*popenargs, **kwargs):
    kw = {}
    kw.update(kwargs)
    dryRun = False
    if 'dryRun' in kw:
        dryRun = kw['dryRun']
        del kw['dryRun']
    if dryRun:
        print popenargs
    else:
        # convert something like run("ls -l") into run("ls -l",shell=True)
        if isinstance(popenargs[0],str) and len(popenargs[0].split()) > 1:
            kw.setdefault("shell",True)
        if options.debug > 0:
            print popenargs
        returncode = call(*popenargs,**kw)
        if returncode != 0:
            raise CalledProcessError(returncode=returncode)

def backsticks(*popenargs,**kwargs):
    """Similar to shell backsticks, e.g. a = `ls -1` <=> a = backsticks(['ls','-1']).
    If 'dryRun=True' is given as keyword argument, then 'dryRet' keyword must provide a value
    to return from this function."""
    kw = {}
    kw.update(kwargs)
    dryRun = False
    if 'dryRun' in kw:
        dryRun = kw['dryRun']
        del kw['dryRun']
    dryRet = None
    if 'dryRet' in kw:
        dryRet = kw['dryRet']
        del kw['dryRet']
    if dryRun:
        print popenargs
        return dryRet
    else:
        if options.debug > 0:
            print popenargs
        kw['stdout'] = PIPE
        p = Popen(*popenargs, **kw)
        retout = p.communicate()[0]
        if p.returncode != 0:
            raise CalledProcessError(returncode=returncode)
        return retout


def varsub(template,*l,**kw):
    o = {}
    p = []
    for x in l:
        if isinstance(x,Struct):
            o.update(x.asDict())
        else:
            p.append(x)
    o.update(kw)
    return string.Template(template).substitute(*p,**o)

def makeTmpFile(*l,**kw):
    """Create and open a temporary file that will exist after this program closes it.
    Return a tuple (file object,file name).
    It does the same as tempfile.NamedTemporaryFile but the file is not automatically
    deleted after being closed. Because it works through calls to mkstemp and os.fdopen,
    the returned file object does not have a file name in its 'name' attribute.
    @param createParents - if True (default) - create parent directories (require 'dir' option)
    @param dir - create file in this directory
    @param mode (default 'w') - open file in this mode
    @param bufsize - open with his buffer size"""
    
    opts1 = {}
    opts1.update(kw)
    opts1.setdefault("createParents",True)
    if opts1.pop("createParents"):
        try:
            dirName = opts1["dir"]
        except KeyError:
            raise ValueError("makeTmpFile: 'dir' keyword must be used with 'createParents' keyword")
        makedir(dirName)
    l2 = []
    opts1.setdefault("mode","w")
    for k in ("mode","bufsize"):
        if opts1.has_key(k):
            l2.append(opts1[k])
            del opts1[k]
    (fd,name) = mkstemp(*l,**opts1)
    return (os.fdopen(fd,*l2),name)

def makedir(path,dryRun=False):
    run(["mkdir","-p",path],dryRun=dryRun)

def makeFilePath(fileName):
    """Assume that the argument is a file name and make all directories that are part of it"""
    dirName = os.path.dirname(fileName)
    if dirName not in ("","."):
        makedir(dirName)

#perhaps use shutil.rmtree instead?    
def rmdir(path,dryRun=False):
    run(["rm","-rf",path],dryRun=dryRun)

rmrf = rmdir

def rmf(path,dryRun=False):
    try:
        os.remove(path)
    except OSError:
        pass

def chmod(path,mode,opts='',dryRun=False):
    if isinstance(path,basestring):
        path = [path]
    else:
        path = list(path)
    run(["chmod"]+opts.split()+[mode]+path,dryRun=dryRun)

def strToFile(s,fileName,mode="w",dryRun=False):
    if not dryRun:
        out = open(fileName,mode)
        out.write(s)
        out.close()
    else:
        print "Write to file %s mode %s:" % (fileName,mode)
        print s

def stripSfx(s,sep='.'):
    """Remove right-most instance of separator string and everything past it.
    Primary use is to remove the file name 'extension'.
    @return input string s without the suffix or original input if suffix is not found"""
    return s.rsplit(sep,1)[0]


def strFilter(s,allowed):
    allowed = set(allowed)
    return ''.join(( x for x in s if x in allowed ))

_osNameFilter_allowedDef = set(string.ascii_letters + string.digits)

def osNameFilter(s,allowed=_osNameFilter_allowedDef):
    return strFilter(s,allowed=allowed)

class SymbolRunsCompressor:

    def __init__(self,sym,minLen):
        assert len(sym) == 1
        self.rex = re.compile('%s{%i,}'%(sym,minLen+1))
        self.rep = sym*minLen

    def __call__(self,s):
        return re.sub(self.rex,self.rep,s)

def isSamePath(path1,path2):
    paths = [ os.path.abspath(os.path.realpath(p)) for p in (path1,path2) ]
    return paths[0] == paths[1]

def openCompressed(filename,mode,**kw):
    if filename.endswith('.gz'):
        return openGzip(filename,mode,**kw)
    else:
        return open(filename,mode,2**20,**kw)

def openGzip(filename,mode,compresslevel=6):
    compresslevel = int(compresslevel)
    if mode in ("w","wb"):
        return Popen("gzip -%s > %s" % (compresslevel,filename), shell=True, env=os.environ, bufsize=2**16, stdin=PIPE, close_fds=True).stdin
    elif mode in ("r","rb"):
        return Popen(("gzip -cd %s" % (filename,)).split(),env=os.environ, bufsize=2**16, stdout=PIPE, close_fds=True).stdout
    else:
        raise ValueError("'openGzip()' - Unsupported 'mode': " + mode)


def strAttributes(o,exclude=tuple(),delim=' | '):
    """Return a string with all attributes names and value for an object 'o'."""
    return delim.join([ name + ' : ' + str(val) for (name,val) in o.__dict__.items()
        if not name in exclude])

def delAttr(o,attr,silent=True):
    try:
        delattr(o,attr)
    except AttributeError:
        if not silent:
            raise


class FastaReaderSink(object):
    
    def __call__(self,lineSeq):
        pass
    
class FastaReaderSinkMem(FastaReaderSink):
    
    def __init__(self):
        from cStringIO import StringIO
        self.seq = StringIO()
        
    def __call__(self,lineSeq):
        self.seq.write(lineSeq.rstrip("\n"))
        
    def sequence(self):
        return self.seq.getvalue()
    
    def close(self):
        self.seq.close()




def seqIterLengths(recIter):
    return numpy.fromiter((rec.seqLen() for rec in recIter),int)

def seqIterLengthsHistogram(recIter,*l,**kw):
    return numpy.histogram(seqIterLengths(recIter),*l,**kw)

class FastaRecord(object):
    def __init__(self, title, sequence):
        """'sequence' can be either a string or an integer length"""
        self.title = title
        self.sequence = sequence
        
    def __str__(self):
        hdr = '>'+self.title
        if self.hasSeq():
            return  hdr + '\n' + \
                '\n'.join([ self.sequence[i:i+70] for i in range(0,len(self.sequence),70) ])
        else:
            return hdr
    
    def hasSeq(self):
        return isinstance(self.sequence,str)
    
    def seqLen(self):
        if self.hasSeq():
            return len(self.sequence)
        else:
            return int(self.sequence)

def writeSeqByLines(out,seq,lineLen=70):
    for i in range(0,len(seq),lineLen):
        out.write(seq[i:i+lineLen])
        out.write("\n")

def readFastaRecords(infile,readSeq=True):
    saved = None
    while 1:
        # Look for the start of a record
        if saved is not None:
            line = saved
            saved = None
        else:
            line = infile.readline()
            if not line:
                return
        
        # skip blank lines
        if line.isspace():
            continue
        
        # Double-check that it's a title line
        if not line.startswith(">"):
            raise TypeError(
                "The title line must start with a '>': %r" % line)
        
        title = line.rstrip()[1:]
        
        # Read the sequence lines until the next record, a blank
        # line, or the end of file
        sequences = []
        seqLen = 0
        
        while 1:
            line = infile.readline()
            if not line or line.isspace():
                break
            if line.startswith(">"):
                # The start of the next record
                saved = line
                break
            ln = line.rstrip("\n")
            if readSeq:
                sequences.append(ln)
            else:
                seqLen += len(ln)
        
        if readSeq:
            seq = "".join(sequences)
        else:
            seq = seqLen
        yield FastaRecord(title, seq)

def splitFastaFile(inpFile,outBase,maxChunkSize):
    inpFile = open(inpFile,'r')
    inp = readFastaRecords(inpFile)
    out = None
    iChunk = 0
    chunkSize = 0
    for rec in inp:
        recSize = len(rec.sequence)
        if out is None or chunkSize + recSize > maxChunkSize:
            if out is not None:
                out.close()
            out = outBase+'_%04d'%(iChunk,)
            out = open(out,'w')
            iChunk += 1
            chunkSize = 0
        out.write('%s\n'%(rec,))
        chunkSize += recSize
    out.close()
    inpFile.close()
    return iChunk



class HistogramRdnGenerator:
    """When initialized with a histogram (as returned by numpy.histogram(...,norm=False), 
    will generate random number distributed in the same way.
    See: http://mathworld.wolfram.com/DistributionFunction.html"""
    
    def __init__(self,hist):
        self.hist = hist
        D = numpy.add.accumulate(hist[0]).astype(float)
        D = D / D[-1]
        self.D = D
        X = hist[1]
        self.X = X
        X_mid = numpy.zeros(len(X),float)
        for i in range(len(X)-1):
            X_mid[i] = (X[i] + X[i+1])/2
        X_mid[-1] = X[-1] + (X[-1]-X_mid[-2])
        D_l = numpy.roll(D,1)
        D_l[0] = 0
        self.D_l = D_l
        self.X_mid = X_mid
        self.eps = numpy.finfo(float).eps
        
    def __call__(self):
        D = self.D
        D_l = self.D_l
        X = self.X
        X_mid = self.X_mid
        y = nrnd.ranf()
        i = D.searchsorted(y)
        if D[i] - D_l[i] < self.eps:
            #random point within the current bin
            return X_mid[i] + (nrnd.ranf()-0.5)*2*(X_mid[i]-X[i])
        else:
            #linear interpolation within the bin
            return X[i] + (X_mid[i] - X[i]) * 2 * (y-D_l[i])/(D[i]-D_l[i])

    def histogram(self):
        return self.hist

def test_HistogramRdnGenerator():
    nIter = 3000
    meansSample = numpy.zeros(nIter)
    meansDistr = meansSample.copy()
    for iter in range(nIter):
        sample = nrnd.ranf(100)    
        #sample = numpy.arange(1000)
        sampleHist = numpy.histogram(sample,bins=10,normed=False)
        gen = HistogramRdnGenerator(sampleHist)
        distr = numpy.array([ gen() for i in range(len(sample)) ])
        distrHist = numpy.histogram(distr,bins=sampleHist[1],normed=False)
        meansSample[iter] = numpy.mean(sample)
        meansDistr[iter] = numpy.mean(distr)
    print distrHist, numpy.mean(distr)
    print sampleHist, numpy.mean(sample)
    print "meanDiff = ", numpy.mean(meansSample-meansDistr)


def seqLengthDistribFromSample(recIter,*l,**kw):
    lenHist = seqIterLengthsHistogram(recIter,*l,**kw)
    gen = HistogramRdnGenerator(lenHist)
    return gen

def masksToInd(maskVal,maskInd):
    """Convert value[0:someN] and index[0:someN] into value[index]. 
    Assumes N->1 relation between index and value. In particular, that means
    value[i] == 0 && value[j] != 0 && index[i] == index[j] is not allowed.
    No checking is made for the above prerequsite - the caller is responsible."""
    val = numpy.zeros(numpy.max(maskInd)+1,dtype=maskVal.dtype)
    val[maskInd] = maskVal
    return val
    
def whereItems(arr,condition):
    wh = numpy.where(condition)
    return numpy.rec.fromarrays((wh[0],arr[wh]),names='ind,val')

def fromWhereItems(whItems,defVal=0):
    wh =  whItems['ind']
    a = numpy.empty(numpy.max(wh) + 1, dtype = whItems['val'].dtype)
    a[:] = defVal
    a[wh] = whItems['val']
    return a

def logicalAnd(*arrays):
    res = n.logical_and(arrays[0],arrays[1])
    if len(arrays) == 2:
        return res
    for a in arrays[2:]:
        res = n.logical_and(res,a)
    return res

def binCount(seq):
    cnt = {}
    for x in seq:
        try:
            cnt[x] += 1
        except KeyError:
            cnt[x] = 1
    return cnt


def selFieldsArray(arr,fields):
    return n.rec.fromarrays([arr[f] for f in fields],names=','.join(fields))

def permuteObjArray(arr):
    #numpy permutation or shuffle do not work on arrays with 'O' datatypes
    return arr[nrnd.permutation(n.arange(len(arr),dtype=int))]

def groupPairs(data,keyField=0):
    """Create a dict(key->list of vals) out of a sequence of pairs (key,val).
    @param data sequence of pairs
    @param keyField index of field to use as key (the remaining field is used as val"""
    x = {}
    assert keyField in (0,1)
    valField = 1 - keyField
    for rec in data:
        key = rec[keyField]
        val = rec[valField]
        try:
            x[key].append(val)
        except KeyError:
            x[key] = [ val ]
    return x


def groupRecArray(arr,keyField):
    """Create a dict(key->record array) out of record array.
    Similar to creating a non-unique database index or sorting by a given field, 
    with the exception that the data is copied inside the index.
    @param arr Numpy record array
    @param keyField name of field to create the key from
    @return dict that for each unique value of keyField contains a numpy record 
    array with all records that have this key value."""
    m = defdict(list)
    for rec in arr:
        m[rec[keyField]].append(rec)
    for key in m:
        m[key] = n.asarray(m[key],dtype=arr.dtype)
    return m


def isUniqueArray(arr):
    return len(n.unique1d(arr)) == len(n.ravel(arr))

class SubSamplerUniRandomEnd:
    """Uniform random [0,rnd_length] subsampler where rnd_length is in [minLen,maxLen]"""

    def __init__(self,minLen,maxLen):
        assert minLen > 0 and maxLen >= minLen
        self.minLen = minLen
        self.maxLen = maxLen

    def __call__(self,samp):
        """Return subsequence [0,random).
        We always take from the beginning rather than from a random start,
        because when subsampling short taxa with concatenation, this gives 
        a better chance of not hitting spacer junction."""
        sampLen = len(samp)
        return samp[0:nrnd.random_integers(min(sampLen,self.minLen),min(sampLen,self.maxLen))]

class SubSamplerRandomStart:
    """random [rnd_start,rnd_start+rnd_length] subsampler where rnd_length is in [minLen,maxLen]"""

    def __init__(self,minLen,maxLen=None):
        if maxLen is None:
            maxLen = minLen
        assert minLen > 0 and maxLen >= minLen
        self.minLen = minLen
        self.maxLen = maxLen

    def __call__(self,samp):
        """Return subsequence [random,random).
        We always take from the beginning rather than from a random start,
        because when subsampling short taxa with concatenation, this gives 
        a better chance of not hitting spacer junction."""
        sampLen = len(samp)
        fragLen = nrnd.random_integers(min(sampLen,self.minLen),min(sampLen,self.maxLen))
        fragStart = nrnd.random_integers(0,sampLen-fragLen)
        return samp[fragStart:fragStart+fragLen]


def getRectStencil(arr,center,halfSize):
    """Return a stencil from Numpy 2D array"""
    center = n.asarray(center)
    ind = n.clip((center-halfSize,center+halfSize+1),(0,0),n.asarray(arr.shape)-1)
    sel = arr[ind[0][0]:ind[1][0],ind[0][1]:ind[1][1]]
    #print center, halfSize, ind, sel
    return sel,ind
