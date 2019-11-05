from numba import jit
import numpy as np
from . import ProbMath
from . import NumbaUtils


def diploidHMM(ind, paternalHaplotypes, maternalHaplotypes, error, recombinationRate, callingMethod = "dosages", useCalledHaps = True, includeGenoProbs = False): 

    nLoci = len(ind.genotypes)

    # !!!! NEED TO MAKE SURE SOURCE HAPLOTYPES ARE ALL NON MISSING!!!
    if type(paternalHaplotypes) is list or type(paternalHaplotypes) is tuple:
        paternalHaplotypes = np.array(paternalHaplotypes)

    if type(maternalHaplotypes) is list or type(maternalHaplotypes) is tuple:
        maternalHaplotypes = np.array(maternalHaplotypes)
    
    if type(error) is float:
        error = np.full(nLoci, error, dtype = np.float32)

    if type(recombinationRate) is float:
        recombinationRate = np.full(nLoci, recombinationRate, dtype = np.float32)
    # !!!! May need to have marker specific error/recombination rates.


    ### Build haploid HMM. 
    ###Construct penetrance values

    if useCalledHaps:
        pointEst = getDiploidPointEstimates(ind.genotypes, ind.haplotypes[0], ind.haplotypes[1], paternalHaplotypes, maternalHaplotypes, error)
    else:
        probs = ProbMath.getGenotypeProbabilities_ind(ind)
        pointEst = getDiploidPointEstimates_probs(probs, paternalHaplotypes, maternalHaplotypes, error)

    
    # if prior is not None:
    #     addDiploidPrior(pointEst, prior)

    ### Run forward-backward algorithm on penetrance values.

    hapEst = diploidForwardBackward(pointEst, recombinationRate)
    # for i in range(nLoci) :
    #     print(hapEst[:,:,i])
    # raise Exception()


    if callingMethod == "dosages" :
        dosages = getDiploidDosages(hapEst, paternalHaplotypes, maternalHaplotypes)
        ind.dosages = dosages

    if callingMethod == "probabilities" :
        values = getDiploidProbabilities(hapEst, paternalHaplotypes, maternalHaplotypes)
        ind.info = values

    if callingMethod == "callhaps":
        raise ValueError("callhaps not yet implimented.")
    if callingMethod == "viterbi" :
        raise ValueError("Viterbi not yet implimented.")

@jit(nopython=True)
def addDiploidPrior(pointEst, prior):
    nPat, nMat, nLoci = pointEst.shape
    for i in range(nLoci):
        for j in range(nPat):
            for k in range(nMat):
                pointEst[j,k,i] *= prior[j,k]

@jit(nopython=True)
def getDiploidDosages(hapEst, paternalHaplotypes, maternalHaplotypes):
    nPat, nLoci = paternalHaplotypes.shape
    nMat, nLoci = maternalHaplotypes.shape
    dosages = np.full(nLoci, 0, dtype = np.float32)
    for i in range(nLoci):
        for j in range(nPat):
            for k in range(nMat):
                dosages[i] += hapEst[i,j,k]*(paternalHaplotypes[j,i] + maternalHaplotypes[k,i])
    return dosages

@jit(nopython=True)
def getDiploidProbabilities(hapEst, paternalHaplotypes, maternalHaplotypes):
    nPat, nLoci = paternalHaplotypes.shape
    nMat, nLoci = maternalHaplotypes.shape
    probs = np.full((4, nLoci), 0, dtype = np.float32)
    for i in range(nLoci):
        for j in range(nPat):
            for k in range(nMat):
                if paternalHaplotypes[j, i] == 0 and maternalHaplotypes[k, i] == 0:
                    probs[0, i] += hapEst[j, k, i]

                if paternalHaplotypes[j, i] == 0 and maternalHaplotypes[k, i] == 1:
                    probs[1, i] += hapEst[j, k, i]

                if paternalHaplotypes[j, i] == 1 and maternalHaplotypes[k, i] == 0:
                    probs[2, i] += hapEst[j, k, i]

                if paternalHaplotypes[j, i] == 1 and maternalHaplotypes[k, i] == 1:
                    probs[3, i] += hapEst[j, k, i]
    return probs

@jit(nopython=True)
def getDiploidPointEstimates(indGeno, indPatHap, indMatHap, paternalHaplotypes, maternalHaplotypes, error):
    nPat, nLoci = paternalHaplotypes.shape
    nMat, nLoci = maternalHaplotypes.shape

    pointEst = np.full((nLoci, nPat, nMat), 1, dtype = np.float32)
    for i in range(nLoci):
        if indGeno[i] != 9:
            for j in range(nPat):
                for k in range(nMat):
                    # Seperate Phased vs non phased loci 
                    if indPatHap[i] != 9 and indMatHap[i] != 9:
                        value = 1
                        if indPatHap[i] == paternalHaplotypes[j, i]:
                            value *= (1-error[i])
                        else:
                            value *= error[i]
                        if indMatHap[i] == maternalHaplotypes[k, i]:
                            value *= (1-error[i])
                        else:
                            value *= error[i]
                        pointEst[i,j,k] = value
                    else:
                        #I think this shouldn't be too horrible.
                        sourceGeno = paternalHaplotypes[j, i] + maternalHaplotypes[k,i]
                        if sourceGeno == indGeno[i]:
                            pointEst[i,j,k,] = 1-error[i]*error[i]
                        else:
                            pointEst[i,j,k] = error[i]*error[i]
    return pointEst

@jit(nopython=True)
def getDiploidPointEstimates_geno(indGeno, paternalHaplotypes, maternalHaplotypes, error, pointEst):
    nPat, nLoci = paternalHaplotypes.shape
    nMat, nLoci = maternalHaplotypes.shape

    for i in range(nLoci):
        if indGeno[i] != 9:
            error_2 = error[i]*error[i]
            for j in range(nPat):
                for k in range(nMat):

                    #I think this shouldn't be too horrible.
                    sourceGeno = paternalHaplotypes[j, i] + maternalHaplotypes[k,i]
                    if sourceGeno == indGeno[i]:
                        pointEst[i,j,k,] = 1-error_2
                    else:
                        pointEst[i,j,k] = error_2

@jit(nopython=True)
def getDiploidPointEstimates_probs(indProbs, paternalHaplotypes, maternalHaplotypes, error):
    nPat, nLoci = paternalHaplotypes.shape
    nMat, nLoci = maternalHaplotypes.shape

    pointEst = np.full((nPat, nMat, nLoci), 1, dtype = np.float32)
    for i in range(nLoci):
        for j in range(nPat):
            for k in range(nMat):
                # I'm just going to be super explicit here. 
                p_aa = indProbs[0, i]
                p_aA = indProbs[1, i]
                p_Aa = indProbs[2, i]
                p_AA = indProbs[3, i]
                e = error[i]
                if paternalHaplotypes[j,i] == 0 and maternalHaplotypes[k, i] == 0:
                    value = p_aa*(1-e)**2 + (p_aA + p_Aa)*e*(1-e) + p_AA*e**2

                if paternalHaplotypes[j,i] == 1 and maternalHaplotypes[k, i] == 0:
                    value = p_Aa*(1-e)**2 + (p_aa + p_AA)*e*(1-e) + p_aA*e**2

                if paternalHaplotypes[j,i] == 0 and maternalHaplotypes[k, i] == 1:
                    value = p_aA*(1-e)**2 + (p_aa + p_AA)*e*(1-e) + p_Aa*e**2

                if paternalHaplotypes[j,i] == 1 and maternalHaplotypes[k, i] == 1:
                    value = p_AA*(1-e)**2  + (p_aA + p_Aa)*e*(1-e) + p_aa*e**2

                pointEst[j,k,i] = value
    return pointEst


@jit(nopython=True)
def diploid_normalize(array):
    """Normalize a 'diploid' probability array in place
    The array should have shape: (# paternal haplotypes, # maternal haplotypes, # loci)
    The function normalizes such that the values at each locus sum to 1

    It's possible the accuracy could be improved by using a compensated summation algorithm, e.g.:
    https://en.wikipedia.org/wiki/Kahan_summation_algorithm
    As it stands, running np.sum(array, axis=(0,1)) on the output of this function with an array
    of shape (200,200,1000) gives values that differ from 1 by ~1e-4
    Note also that Numba doesn't support axis=(0,1)"""

    n_pat, n_mat, n_loci = array.shape
    for i in range(n_loci):
        # Use a float64 accumulator to avoid losing precision
        sum_ = np.float64(0)
        for j in range(n_pat):
            for k in range(n_mat):
                sum_ += array[j,k,i]
        for j in range(n_pat):
            for k in range(n_mat):
                array[j,k,i] = array[j,k,i]/sum_


# @jit(nopython=True)
# def diploidTransformProbs(previous, estimate, point_estimate, recombination_rate, new, pat, mat):
#     """Transforms a probability distribution (over pairs of paternal and maternal haplotypes, at a single locus)
#     to a probability distribution at the next locus by accounting for emission probabilities (point_estimates)
#     and transition probabilities (recombination_rate)

#     This is a core step in the forward and backward algorithms

#     point_estimates     emission probabilities
#                         shape: (# paternal haplotypes, # maternal haplotypes)
#     recombination_rate  recombination rate at this locus - scalar
#     previous            probability distribution over pairs of haplotypes (hidden states) at the *previous* locus
#                         shape: (# paternal haplotypes, # maternal haplotypes)
#     estimate            newly calculated probability distribution over pairs of haplotypes at *this* locus
#                         shape: (# paternal haplotypes, # maternal haplotypes)

#     Note: previous and estimate are updated by this function"""

#     n_pat, n_mat = point_estimate.shape

#     # Get estimate at this locus and normalize
#     # for j in range(n_pat):
#     #     for k in range(n_mat):
#     #         new[j, k] = previous[j, k]*point_estimate[j, k]
#     new[:,:] = previous*point_estimate
#     new /= np.sum(new)
#     # sum_ = np.float64(0)
#     # for j in range(n_pat):
#     #     for k in range(n_mat):
#     #         sum_ += new[j, k]
#     # for j in range(n_pat):
#     #     for k in range(n_mat):
#     #         new[j, k] = new[j, k]/sum_

#     # Get haplotype specific recombinations
#     pat[:] = 0
#     mat[:] = 0
#     for j in range(n_pat):
#         for k in range(n_mat):
#             pat[j] += new[j, k]
#             mat[k] += new[j, k]
    
#     e = recombination_rate
#     e1e = (1-e)*e
#     e2m1 = (1-e)**2

#     # Adding modifications to pat and mat to take into account number of haplotypes and recombination rate.
#     pat *= e1e/n_pat
#     mat *= e1e/n_mat

#     e2 = e*e/(n_mat*n_pat)

#     # Account for recombination rate
#     for j in range(n_pat):
#         for k in range(n_mat):
#             new[j, k] = new[j, k]*e2m1 + pat[j] + mat[k] + e2

#     # Update distributions (in place)
#     for j in range(n_pat):
#         for k in range(n_mat):
#             estimate[j, k] *= new[j, k]
#             previous[j, k] = new[j, k]



@jit(nopython=True)
def transmit(previous_estimate, recombination_rate, output, pat, mat):
    """Transforms a probability distribution (over pairs of paternal and maternal haplotypes, at a single locus)
    to a probability distribution at the next locus by accounting for emission probabilities (point_estimates)
    and transition probabilities (recombination_rate)

    This is a core step in the forward and backward algorithms

    point_estimates     probability distribution to be transmitted forward. Assume already normalized.
                        shape: (# paternal haplotypes, # maternal haplotypes)
    recombination_rate  recombination rate at this locus - scalar
    forward_i           newly calculated probability distribution over pairs of haplotypes at *this* locus
                        shape: (# paternal haplotypes, # maternal haplotypes)

    Note: previous and estimate are updated by this function"""

    n_pat, n_mat = previous_estimate.shape

    # Get haplotype specific recombinations
    pat[:] = 0
    mat[:] = 0
    for j in range(n_pat):
        for k in range(n_mat):
            pat[j] += previous_estimate[j, k]
            mat[k] += previous_estimate[j, k]
    
    e = recombination_rate
    e1e = (1-e)*e
    e2m1 = (1-e)**2

    # Adding modifications to pat and mat to take into account number of haplotypes and recombination rate.
    pat *= e1e/n_pat
    mat *= e1e/n_mat

    e2 = e*e/(n_mat*n_pat)

    # Account for recombinations
    for j in range(n_pat):
        for k in range(n_mat):
            output[j, k] = previous_estimate[j, k]*e2m1 + pat[j] + mat[k] + e2


@jit(nopython=True)
def diploid_forward(point_estimate, recombination_rate, in_place = False):
    """Calculate forward probabilities combined with the point_estimates"""

    n_loci, n_pat, n_mat = point_estimate.shape
    if in_place :
        combined = point_estimate
    else:
        combined = point_estimate.copy()  # copy so that point_estimate is not modified

    prev = np.full((n_pat, n_mat), 0.25, dtype=np.float32)

    # Temporary numba variables.
    forward_i = np.empty((n_pat, n_mat), dtype=np.float32)
    tmp_pat = np.empty(n_pat, dtype=np.float32)
    tmp_mat = np.empty(n_mat, dtype=np.float32)

    # Make sure the first locus is normalized.
    combined[0,:,:] /= np.sum(combined[:,:])
    for i in range(1, n_loci): 
        # Update estimates at this locus

        # Take the value at locus i-1 and transmit it forward.
        transmit(combined[i-1,:,:], recombination_rate[i], forward_i, tmp_pat, tmp_mat)

        # Combine the forward estimate at locus i with the point estimate at i.
        # This is safe if in_place = True since we have not updated combined[i,:,:] yet and it will be still equal to point_estimate.
        combined[i,:,:] = point_estimate[i,:,:] * forward_i
        combined[i,:,:] /= np.sum(combined[i,:,:])

    return combined


@jit(nopython=True)
def diploid_backward(point_estimate, recombination_rate):
    """Calculate backward probabilities"""

    n_loci, n_pat, n_mat = point_estimate.shape
    backward = np.ones_like(point_estimate, dtype=np.float32)

    prev = np.full((n_pat, n_mat), 0.25, dtype=np.float32)

    # Temporary numba variables.
    combined_i = np.empty((n_pat, n_mat), dtype=np.float32)
    tmp_pat = np.empty(n_pat, dtype=np.float32)
    tmp_mat = np.empty(n_mat, dtype=np.float32)

    for i in range(n_loci-2, -1, -1): 
        # Skip the first loci.
        # Combine the backward estimate at i+1 with the point estimate at i+1 (unlike the forward pass, the backward estimate does not contain the point_estimate).
        combined_i[:,:] = backward[i+1,:,:] * point_estimate[i+1,:,:]
        combined_i[:,:] /= np.sum(combined_i)

        # Transmit the combined value forward. This is the backward estimate.
        transmit(combined_i, recombination_rate[i], backward[i, :,:], tmp_pat, tmp_mat)

    return backward


@jit(nopython=True)
def diploidForwardBackward(point_estimate, recombination_rate):
    """Calculate state probabilities at each loci using the forward-backward algorithm"""

    # We may want to split this out into something else.

    est = diploid_backward(point_estimate, recombination_rate)
    est *= diploid_forward(point_estimate, recombination_rate, in_place = True)

    # Return normalized probabilities
    # diploid_normalize(est)
 
    n_loci = est.shape[0]
    for i in range(n_loci):
        est[i,:,:]/=np.sum(est[i, :, :])

    return est



@jit(nopython=True)
def diploidSampleHaplotypes(forward_probs, recombination_rate, paternal_haplotypes, maternal_haplotypes):
    """Sample a pair of paternal and maternal haplotypes from the forward and backward probability distributions 
    and paternal and maternal haplotype libraries.
    Returns:
      haplotypes      Pair of haplotypes as a 2D array of shape (2, n_loci)
    """
    n_loci = forward_probs.shape[0]
    haplotypes = np.full((2, n_loci), 9, dtype=np.int8)
    paternal_indices, maternal_indices = diploidOneSample(forward_probs, recombination_rate)
    haplotypes[0] = haplotypeFromHaplotypeIndices(paternal_indices, paternal_haplotypes)
    haplotypes[1] = haplotypeFromHaplotypeIndices(maternal_indices, maternal_haplotypes)
    
    return haplotypes


@jit(nopython=True)
def diploidOneSample(forward_probs, recombination_rate):
    """Sample a pair of paternal and maternal haplotypes from the forward and backward probability distributions
    Returns:
      paternal_indices, maternal_indices - arrays of sampled haplotype indices 
      
    A description of the sampling process would be nice here..."""

    n_loci , n_pat, n_mat= forward_probs.shape

    pvals = np.empty((n_pat, n_mat), dtype=np.float32)  # sampled probability distribution at one locus
    paternal_indices = np.empty(n_loci, dtype=np.int64)
    maternal_indices = np.empty(n_loci, dtype=np.int64)
    
    # Backwards algorithm
    for i in range(n_loci-1, -1, -1): # zero indexed then minus one since we skip the boundary
        # Sample at this locus
        if i == n_loci-1:
            pvals[:,:] = forward_probs[i, :, :]
        else:
            combine_backward_sampled_value(forward_probs[i,:,:], paternal_indices[i+1], maternal_indices[i+1], recombination_rate[i+1], pvals[:,:])

        j, k = NumbaUtils.multinomial_sample_2d(pvals=pvals) 
        paternal_indices[i] = j
        maternal_indices[i] = k

    # Last sample (at the first locus)
    j, k = NumbaUtils.multinomial_sample_2d(pvals=pvals) 
    paternal_indices[0] = j
    maternal_indices[0] = k

    return paternal_indices, maternal_indices


@jit(nopython=True)
def diploidIndices(sampled_probs):
    """Get paternal and maternal indices from sampled probability distribution
    Intended to be used with sampled probabilities as returned from diploidOneSample()"""
    
    n_loci, n_pat, n_mat = sampled_probs.shape
    paternal_indices = np.empty(n_loci, dtype=np.int64)
    maternal_indices = np.empty(n_loci, dtype=np.int64)
    
    eps = np.finfo(np.float32).eps
    for i in range(n_loci):
        for j in range(n_pat):
            for k in range(n_mat):
                # If sampled_probs[j, k, i] == 1
                # set indices array to values j and k
                if sampled_probs[i, j, k] > 1-eps: 
                    paternal_indices[i] = j
                    maternal_indices[i] = k
                    
    return paternal_indices, maternal_indices


@jit(nopython=True)
def combine_backward_sampled_value(previous_estimate, pat_hap, mat_hap, recombination_rate, output):
    """Includes information from the previous sampled locus into the estimate at the current sampled locus.

    previous_estimate   combination of the forward + point estimate at the locus.
                        shape: (# paternal haplotypes, # maternal haplotypes)
    pat_hap, mat_hap    Sampled paternal and maternal haplotypes -- integer
    recombination_rate  recombination rate at this locus - scalar
    forward_i           newly calculated probability distribution over pairs of haplotypes at *this* locus
                        shape: (# paternal haplotypes, # maternal haplotypes)

    Note: previous and estimate are updated by this function"""


    n_pat, n_mat = previous_estimate.shape

    e = recombination_rate
    single_rec = (1-e)*e
    no_rec = (1-e)**2
    double_rec = e*e


    # Haplotype is moving from pat_hap, mat_hap.
    # Double recombination -- both haplotypes change.
    output[:,:] = double_rec/(n_mat*n_pat)

    # Maternal recombination -- pat_hap stays the same.
    for k in range(n_mat):
        output[pat_hap, k] += single_rec/n_mat

    # Paternal recombination -- mat_hap stays the same.
    for j in range(n_pat):
        output[j, mat_hap] += single_rec/n_pat

    # No recombinations -- both haplotypes stay the same.
    output[pat_hap, mat_hap] += no_rec

    # Add in forward_plus_combined
    output *= previous_estimate
    return output


