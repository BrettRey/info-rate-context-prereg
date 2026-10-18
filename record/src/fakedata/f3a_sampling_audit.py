"""Analytic audit of the shape's log-SR mean sampling covariance, no data values."""
import importlib.util
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sampling_audit_design',HERE/'f3a_design.py')
D=importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


def mean_error_covariance(shape, setting='data'):
    """First-order log-mean error covariance under the declared crossed process.

    Each observed reading has weight 1/(speakers_in_language *
    readings_for_that_speaker). Speaker weights sum to 1/S. Text weights are
    shared across languages; language-by-text and reading effects are separate.
    This is a linearisation, not a correction applied to the estimates.
    """
    lang,speaker,text=map(np.asarray,shape)
    languages,texts=np.unique(lang),np.unique(text)
    H=np.zeros((len(languages),len(texts)))
    diagonal=np.zeros(len(languages))
    parameters=D.SETTINGS[setting]
    counts=[]
    for j,language in enumerate(languages):
        sel=lang==language
        speakers,si=np.unique(speaker[sel],return_inverse=True)
        sizes=np.bincount(si)
        weights=1/(len(speakers)*sizes[si])
        np.add.at(H[j],np.searchsorted(texts,text[sel]),weights)
        diagonal[j]=(parameters['sd_speaker']**2/len(speakers)+
                     parameters['sd_language_text']**2*np.sum(H[j]**2)+
                     parameters['sd_reading']**2*np.sum(weights**2))
        counts.append(dict(language=str(language),n_speakers=len(speakers),
                           n_readings=int(sel.sum()),missing_cells=int(len(speakers)*len(texts)-sel.sum())))
    covariance=np.diag(diagonal)+parameters['sd_text']**2*H@H.T
    projection=np.eye(len(languages))-np.ones((len(languages),len(languages)))/len(languages)
    centred=projection@covariance@projection
    return dict(languages=languages, covariance=covariance, centred_covariance=centred,
                expected_added_sample_variance=float(np.trace(centred)/(len(languages)-1)),
                text_weights=H, counts=counts)
