import numpy as np
import numba
from numba import jit, int8, int64, boolean, deferred_type, optional, jitclass, float32, double
from collections import OrderedDict
from . import InputOutput
from . import ProbMath




class Family(object):
    """Family is a container for fullsib families"""
    def __init__(self, idn, sire, dam, offspring):
        self.idn = idn
        self.sire = sire
        self.dam = dam
        self.offspring = offspring
        self.generation = max(sire.generation, dam.generation)

        # Add this family to both the sire and dam's family.
        self.sire.families.append(self)
        self.dam.families.append(self)

    def addChild(self, child) :
        self.offspring.append(child)

    def toJit(self):
        """Returns a just in time version of itself with Individuals replaced by id numbers"""
        offspring = np.array([child.idn for child in self.offspring])
        return jit_Family(self.idn, self.sire.idn, self.dam.idn, offspring)


spec = OrderedDict()
spec['idn'] = int64
spec['sire'] = int64
spec['dam'] = int64
spec['offspring'] = int64[:]

@jitclass(spec)
class jit_Family(object):
    def __init__(self, idn, sire, dam, offspring):
        self.idn = idn
        self.sire = sire
        self.dam = dam
        self.offspring = offspring

class Individual(object):
    
    def __init__(self, idx, idn) :

        self.genotypes = None
        self.haplotypes = None
        self.dosages = None

        self.reads = None
        self.longReads = []

        # Do we use this?
        self.genotypeDosages = None
        self.haplotypeDosages = None
        self.hapOfOrigin = None

        # Info is here to provide other software to add in additional information to an Individual.
        self.info = None

        #For plant impute. Inbred is either DH or heavily selfed. Ancestors is historical source of the cross (may be more than 2 way so can't handle via pedigree).
        self.inbred = False
        self.imputationAncestors = [] #This is a list of lists. Either length 0, length 1 or length 2.
        self.selfingGeneration = None

        self.sire = None
        self.dam = None
        self.idx = idx # User inputed string identifier
        self.idn = idn # ID number assigned by the pedigree
        self.fileIndex = dict() # Position of an animal in each file when reading in. Used to make sure Input and Output order are the same.
        self.fileIndex["id"] = idx

        self.dummy = False

        self.offspring = []
        self.families = []

        self.sex = -1
        self.generation = None

        self.initHD = False

        self.genotypedFounderStatus = None #?


    def getPercentMissing(self):
        return np.mean(self.genotypes == 9)

    def getGeneration(self):

        if self.generation is not None : return self.generation

        if self.dam is None: 
            damGen = -1
        else:
            damGen = self.dam.getGeneration()
        if self.sire is None: 
            sireGen = -1
        else:
            sireGen = self.sire.getGeneration()

        self.generation = max(sireGen, damGen) + 1
        return self.generation


    def constructInfo(self, nLoci, genotypes = True,  haps = False, reads = False) :
        if genotypes and self.genotypes is None:
            self.genotypes = np.full(nLoci, 9, dtype = np.int8)
        
        if  haps and self.haplotypes is None:
            self.haplotypes = (np.full(nLoci, 9, dtype = np.int8), np.full(nLoci, 9, dtype = np.int8))

        if reads and self.reads is None:
            self.reads = (np.full(nLoci, 0, dtype = np.int64), np.full(nLoci, 0, dtype = np.int64))
    
    def isFounder(self):
        return (self.sire is None) and (self.dam is None)

    def getGenotypedFounderStatus(self):
        # options: 1: "GenotypedFounder", 0:"ChildOfNonGenotyped", 2:"ChildOfGenotyped"
        if self.genotypedFounderStatus is None:
            if self.isFounder() :
                if self.genotypes is None or np.all(self.genotypes == 9):
                    self.genotypedFounderStatus = 0 
                else:
                    self.genotypedFounderStatus = 1
            else:
                parentStatus = max(self.sire.getGenotypedFounderStatus(), self.sire.getGenotypedFounderStatus())
                if parentStatus > 0:
                    self.genotypedFounderStatus = 2
                else:
                    if self.genotypes is None or np.all(self.genotypes == 9):
                        self.genotypedFounderStatus = 0 
                    else:
                        self.genotypedFounderStatus = 1

        return self.genotypedFounderStatus
    def isGenotypedFounder(self):
        return (self.getGenotypedFounderStatus() == 1)

# Not sure of the code source: https://blog.codinghorror.com/sorting-for-humans-natural-sort-order/
# Slightly modified.
import re 
def sorted_nicely( l , key): 
    """ Sort the given iterable in the way that humans expect.""" 
    convert = lambda text: int(text) if text.isdigit() else text 
    alphanum_key = lambda k: [ convert(c) for c in re.split('([0-9]+)', str(key(k))) ] 
    return sorted(l, key = alphanum_key)

class Pedigree(object):
 
    def __init__(self, fileName = None, constructor = Individual):

        self.maxIdn = 0
        self.maxFam = 0

        self.individuals =dict()
        self.families = None
        self.constructor = constructor
        self.nGenerations = 0
        self.generations = None #List of lists
        self.genFamilies = None #list of lists of families.
        self.truePed = None
        self.nLoci = 0
        
        self.mapSireToFamilies = None
        self.mapDamToFamilies = None

        self.startsnp = 0
        self.endsnp = self.nLoci

        self.referencePanel = [] #This should be an array of haplotypes. Or a dictionary?

        self.maf=None #Maf is the frequency of 2s.

        if fileName is not None:
            self.readInPedigree(fileName)

        self.args = None
        self.writeOrderList = None

    def setupFamilyMap(self):
        self.mapSireToFamilies = dict()
        self.mapDamToFamilies = dict()

        for families in self.genFamilies:
            for family in families:
                sire = family.sire.idn
                dam = family.dam.idn
                fam = family.idn

                if sire not in self.mapSireToFamilies:
                    self.mapSireToFamilies[sire] = []
                self.mapSireToFamilies[sire].append(fam)
        
                if dam not in self.mapDamToFamilies:
                    self.mapDamToFamilies[dam] = []
                self.mapDamToFamilies[dam].append(fam)

    def writeOrder(self):
        if self.writeOrderList is None:
            inds = [ind for ind in self if (not ind.dummy) and (self.args.writekey in ind.fileIndex)]
            self.writeOrderList = sorted_nicely(inds, key = lambda ind: ind.fileIndex[self.args.writekey])
            
            if not self.args.onlykeyed:
                indsNoDummyNoFileIndex = [ind for ind in self if (not ind.dummy) and (not self.args.writekey in ind.fileIndex)]
                self.writeOrderList.extend(sorted_nicely(indsNoDummyNoFileIndex, key = lambda ind: ind.idx))
                
                dummys = [ind for ind in self if ind.dummy]
                self.writeOrderList.extend(sorted_nicely(dummys, key = lambda ind: ind.idx))

        for ind in self.writeOrderList :
            yield (ind.idx, ind)

    def setMaf(self) :
        maf = np.full(self.nLoci, 1, dtype = np.float32)
        counts = np.full(self.nLoci, 2, dtype = np.float32)
        for ind in self.individuals.values():
            if ind.genotypes is not None:
                addIfNotMissing(maf, counts, ind.genotypes)
        
        self.maf = maf/counts

    def getMissingness(self):
        missingness = np.full(self.nLoci, 1, dtype = np.float32)

        counts = 0
        for ind in self.individuals.values():
            if ind.genotypes is not None:
                counts += 1
                addIfMissing(missingness, ind.genotypes)
        return missingness/counts

    def fillIn(self, genotypes = True, haps = False, reads = False):

        for individual in self:
            individual.constructInfo(self.nLoci, genotypes = True, haps = haps, reads = reads)


    def __iter__(self) :
        if self.generations is None:
            self.setUpGenerations()
        for gen in self.generations:
            for ind in gen:
                yield ind

    def __reversed__(self) :
        if self.generations is None:
            self.setUpGenerations()
        for gen in reversed(self.generations):
            for ind in gen:
                yield ind

    def setUpGenerations(self) :
        self.nGenerations = 0
        #We can't use a simple iterator over self here, becuase __iter__ calls this function.
        for idx, ind in self.individuals.items():
            gen = ind.getGeneration()
            self.nGenerations = max(gen, self.nGenerations)
        self.nGenerations += 1 #To account for generation 0. 

        self.generations = [[] for i in range(self.nGenerations)]

        for idx, ind in self.individuals.items():
            gen = ind.getGeneration()
            self.generations[gen].append(ind)

    #This is really sloppy, but probably not important.
    def setupFamilies(self) :

        if self.generations is None:
            self.setUpGenerations()

        self.families = dict()
        for ind in self:
            if not ind.isFounder():
                parents = (ind.sire.idx, ind.dam.idx)
                if parents in self.families :
                    self.families[parents].addChild(ind)
                else:
                    self.families[parents] = Family(self.maxFam, ind.sire, ind.dam, [ind])
                    self.maxFam += 1

        self.genFamilies = [[] for i in range(self.nGenerations)]
        
        for family in self.families.values():
            self.genFamilies[family.generation].append(family)
    
    def setProxys(self) :
        for family in self.families.values():
            family.setProxy()

    def getFamilies(self, rev = False) :
        if self.generations is None:
            self.setUpGenerations()
        if self.families is None:
            self.setupFamilies()

        gens = range(0, len(self.genFamilies))
        if rev: gens = reversed(gens)

        for i in gens:
            print(i)
            for family in self.genFamilies[i]:
                yield family
 
    def getIndividual(self, idx) :
        if idx not in self.individuals:
            self.individuals[idx] = self.constructor(idx, self.maxIdn)
            self.maxIdn += 1
            self.generations = None
        return self.individuals[idx]

    def readInPedigree(self, fileName):
        with open(fileName) as f:
            lines = f.readlines()
        pedList = [line.split() for line in lines]
        self.readInPedigreeFromList(pedList)

    def readInPlantInfo(self, fileName):
        with open(fileName) as f:
            lines = f.readlines()

        for line in lines:
            parts = line.split()
            idx = parts[0]; 

            if idx not in self.individuals:
                self.individuals[idx] = self.constructor(idx, self.maxIdn)
                self.maxIdn += 1

            ind = self.individuals[idx]
            if len(parts) > 1:
                if parts[1] == "DH" or parts[1] == "INBRED":
                    ind.inbred = True
                elif parts[1][0] == "S" :
                    ind.inbred = False
                    ind.selfingGeneration = int(parts[1][1:])
                else:
                    ind.inbred = False

            if len(parts) > 2:
                if "|" in line:
                    first, second = line.split("|")
                    self.addAncestors(ind, first.split()[2:])
                    self.addAncestors(ind, second.split())
                else:
                    self.addAncestors(ind, parts[2:])


    def addAncestors(self, ind, parts):
        ancestors = []
        for idx in parts:
            if idx not in self.individuals:
                self.individuals[idx] = self.constructor(idx, self.maxIdn)
                self.maxIdn += 1
            ancestor = self.individuals[idx]
            ancestors.append(ancestor)
        ind.imputationAncestors.append(ancestors)


    def readInPedigreeFromList(self, pedList):
        index = 0
        for parts in pedList :
            idx = parts[0]
            self.individuals[idx] = self.constructor(idx, self.maxIdn)
            self.maxIdn += 1
            self.individuals[idx].fileIndex['pedigree'] = index; index += 1

        for parts in pedList :
            idx = parts[0]
            if parts[1] == "0": parts[1] = None
            if parts[2] == "0": parts[2] = None
            
            if parts[1] is not None and parts[2] is None:
                parts[2] = "MotherOf"+parts[0]
            if parts[2] is not None and parts[1] is None:
                parts[1] = "FatherOf"+parts[0] 

            ind = self.individuals[parts[0]]
            
            if parts[1] is not None:
                if parts[1] not in self.individuals:
                    self.individuals[parts[1]] = self.constructor(parts[1], self.maxIdn)
                    self.maxIdn += 1
                    self.individuals[parts[1]].fileIndex['pedigree'] = index; index += 1
                    self.individuals[parts[1]].dummy=True

                sire = self.individuals[parts[1]]
                ind.sire = sire
                sire.offspring.append(ind)
                sire.sex = 0

            if parts[2] is not None:
                if parts[2] not in self.individuals:
                    self.individuals[parts[2]] = self.constructor(parts[2], self.maxIdn)
                    self.maxIdn += 1
                    self.individuals[parts[2]].fileIndex['pedigree'] = index; index += 1
                    self.individuals[parts[1]].dummy=True

                dam = self.individuals[parts[2]]
                ind.dam = dam
                dam.offspring.append(ind)
                dam.sex = 1

            if len(parts) > 3:
                if parts[3] == "M" or parts[3] == "m" or parts[3] == "0" or parts[3] == "XY":
                    ind.sex = 0
                elif parts[3] == "F" or parts[3] == "f" or parts[3] == "1" or parts[3] == "XX":
                    ind.sex = 1
                else:
                    ind.sex = 1 #Default to homogemetic.

    def readInFromPlink(self, idList, pedList, bed, externalPedigree = False):
        index = 0

        if not externalPedigree:
            self.readInPedigreeFromList(pedList)
    
        for i, idx in enumerate(idList):
            genotypes=bed[:, i].copy() ##I think this is the right order. Doing the copy to be safe.
            nLoci = len(genotypes)
            if self.nLoci == 0:
                self.nLoci = nLoci
            if self.nLoci != nLoci:
                raise ValueError(f"Incorrect number of loci when reading in plink file. Expected {self.nLoci} got {nLoci}.")
            if idx not in self.individuals:
                self.individuals[idx] = self.constructor(idx, self.maxIdn)
                self.maxIdn += 1

            ind = self.individuals[idx]
            ind.constructInfo(nLoci, genotypes=True)
            ind.genotypes = genotypes

            ind.fileIndex['plink'] = index; index += 1

            if np.mean(genotypes == 9) < .1 :
                ind.initHD = True


    def readInLine(self, line, startsnp, stopsnp, idxExpected = None, ncol = None, dtype = np.int8, getInd = True):
        parts = line.split(); 
        idx = parts[0]

        if idxExpected is not None and idx != idxExpected:
            raise ValueError(f"Expected individual {idxExpected} but got individual {idx}")

        if ncol is None:
            ncol = len(parts)
        if ncol != len(parts):
            raise ValueError(f"Incorrect number of columns in {fileName}. Expected {ncol} values but got {len(parts)} for individual {idx}.")

        parts = parts[1:]
        if startsnp is not None :
            if self.nLoci == 0:
                print("Setting number of loci from start/stopsnp")
                self.nLoci = stopsnp - startsnp + 1 #Override to make sure we get the right number of values.
            parts = parts[startsnp : stopsnp + 1] #Offset 1 for id and 2 for id + include stopsnp
        data=np.array([int(val) for val in parts], dtype = dtype)
        
        nLoci = len(parts)
        if self.nLoci == 0:
            self.nLoci = nLoci
        if self.nLoci != nLoci:
            raise ValueError(f"Incorrect number of values from {fileName}. Expected {self.nLoci} got {nLoci}.")
        ind = None

        if getInd :
            ind = self.getIndividual(idx)

        return ind, data, ncol 

    def readInGenotypes(self, fileName, startsnp=None, stopsnp = None):

        print("Reading in AlphaImpute Format:", fileName)
        index = 0
        
        ncol = None
        with open(fileName) as f:
            for line in f:
                ind, genotypes, ncol = self.readInLine(line, startsnp = startsnp, stopsnp = stopsnp, idxExpected = None, ncol = ncol, dtype = np.int8)

                ind.constructInfo(self.nLoci, genotypes=True)
                ind.genotypes = genotypes

                ind.fileIndex['genotypes'] = index; index += 1

                if np.mean(genotypes == 9) < .1 :
                    ind.initHD = True

    def readInReferencePanel(self, fileName, startsnp=None, stopsnp = None):

        print("Reading in reference panel:", fileName)
        index = 0
        
        ncol = None
        with open(fileName) as f:
            for line in f:
                ind, haplotype, ncol = self.readInLine(line, startsnp = startsnp, stopsnp = stopsnp, idxExpected = None, ncol = ncol, dtype = np.int8, getInd=False)
                self.referencePanel.append(haplotype)

    def readInPhase(self, fileName, startsnp=None, stopsnp = None):
        print("Reading in phase data:", fileName)
        index = 0
        ncol = None

        with open(fileName) as f:
            e = 0
            currentInd = None

            for line in f:
                if e == 0: 
                    idxExpected = None
                else:
                    idxExpected = currentInd.idx

                ind, haplotype, ncol = self.readInLine(line, startsnp = startsnp, stopsnp = stopsnp, idxExpected = idxExpected, ncol = ncol, dtype = np.int8)
                currentInd = ind

                ind.constructInfo(self.nLoci, haps=True)
                ind.haplotypes[e][:] = haplotype
                e = 1-e

                ind.fileIndex['phase'] = index; index += 1

        
    def readInSequence(self, fileName, startsnp=None, stopsnp = None):
        index = 0
        ncol = None

        print("Reading in sequence data :", fileName)
        with open(fileName) as f:
            e = 0
            currentInd = None

            for line in f:
                if e == 0: 
                    idxExpected = None
                else:
                    idxExpected = currentInd.idx

                ind, reads, ncol = self.readInLine(line, startsnp = startsnp, stopsnp = stopsnp, idxExpected = idxExpected, ncol = ncol, dtype = np.int64)
                currentInd = ind

                ind.constructInfo(self.nLoci, reads=True)
                ind.fileIndex['sequence'] = index; index += 1

                ind.reads[e][:] = reads
                e = 1-e
   

    def callGenotypes(self, threshold):
        for idx, ind in self.writeOrder():
            matrix = ProbMath.getGenotypeProbabilities_ind(ind, InputOutput.args)
            
            matrixCollapsedHets = np.array([matrix[0,:], matrix[1,:] + matrix[2,:], matrix[3,:]], dtype=np.float32)
            calledGenotypes = np.argmax(matrixCollapsedHets, axis = 0)
            setMissing(calledGenotypes, matrixCollapsedHets, threshold)
            if InputOutput.args.sexchrom and ind.sex == 0:
                doubleIfNotMissing(calledGenotypes)
            ind.genotypes = calledGenotypes


    def writePedigree(self, outputFile):
        with open(outputFile, 'w+') as f:
            for ind in self:
                sire = "0"
                if ind.sire is not None:
                    sire = ind.sire.idx
                dam = "0"
                if ind.dam is not None:
                    dam = ind.dam.idx
                f.write(ind.idx + ' ' + sire + ' ' + dam + '\n')



    def writeGenotypes(self, outputFile):
        with open(outputFile, 'w+') as f:
            for idx, ind in self.individuals.items():
                self.writeLine(f, ind.idx, ind.genotypes, str)

    def writePhase(self, outputFile):
        with open(outputFile, 'w+') as f:
            for idx, ind in self.individuals.items():

                self.writeLine(f, ind.idx, ind.haplotypes[0], str)
                self.writeLine(f, ind.idx, ind.haplotypes[1], str)



    def writeDosages(self, outputFile):
        with open(outputFile, 'w+') as f:
            for idx, ind in self.individuals.items():
                if ind.dosages is not None:
                    dosages = ind.dosages
                else: 
                    dosages = ind.genotypes.copy()
                    dosages[dosages == 9] = 1
                self.writeLine(f, ind.idx, dosages, "{:.4f}".format)


    def writeGenotypes_prefil(self, outputFile):
        # print("Output is using filled genotypes. Filling missing with a value of 1")
        # fillValues = np.full(1, self.nLoci)

        print("Output is using filled genotypes. Filling missing with rounded allele frequency")
        self.setMaf()
        fillValues = np.round(self.maf)

        with open(outputFile, 'w+') as f:
            for idx, ind in self.individuals.items():
                fill(ind.genotypes, fillValues)
                self.writeLine(f, ind.idx, ind.genotypes, str)

    def writeLine(self, f, idx, data, func) :
        f.write(idx + ' ' + ' '.join(map(func, data)) + '\n')


    # def writeSeg(self, outputFile):
    #     with open(outputFile, 'w+') as f:
    #         for idx, ind in self.individuals.items():
    #             # Imputation.ind_assignOrigin(ind)
    #             if ind.segregation is not None:
    #                 f.write(ind.idx + ' ' + ' '.join(map(str, Imputation.getSegregation(self.nLoci, ind.segregation[0]))) + '\n')
    #                 f.write(ind.idx + ' ' + ' '.join(map(str, Imputation.getSegregation(self.nLoci, ind.segregation[1]))) + '\n')
@jit(nopython=True)
def fill(genotypes, fillValue):
    for i in range(len(genotypes)):
        if genotypes[i] == 9:
            genotypes[i] = fillValue[i]

@jit(nopython=True)
def addIfNotMissing(array1, counts, array2):
    for i in range(len(array1)):
        if array2[i] != 9:
            array1[i] += array2[i]
            counts[i] += 2



@jit(nopython=True)
def addIfMissing(array1, array2):
    for i in range(len(array1)):
        if array2[i] == 9:
            array1[i] += 1

@jit(nopython=True)
def doubleIfNotMissing(calledGenotypes):
    nLoci = len(calledGenotypes)
    for i in range(nLoci):
        if calledGenotypes[i] == 1:
            calledGenotypes[i] = 2

@jit(nopython=True)
def setMissing(calledGenotypes, matrix, thresh) :
    nLoci = len(calledGenotypes)
    for i in range(nLoci):
        if matrix[calledGenotypes[i],i] < thresh:
            calledGenotypes[i] = 9















