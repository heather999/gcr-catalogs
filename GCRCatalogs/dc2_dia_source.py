"""
DC2 Source Catalog Reader
"""

import os
import re
import warnings
import shutil

import numpy as np
import pyarrow.parquet as pq
import yaml

from GCR import BaseGenericCatalog
from .dc2_catalog import DC2Catalog


__all__ = ['DC2DiaSourceCatalog']

FILE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATTERN = r'dia_src_visit_\d+\.parquet$'
SCHEMA_FILENAME = 'schema.yaml'
META_PATH = os.path.join(FILE_DIR, 'catalog_configs/_dc2_dia_source_meta.yaml')

class DC2DiaSourceCatalog(DC2Catalog):
    r"""DC2 DIA Object Catalog reader

    Parameters
    ----------
    base_dir          (str): Directory of data files being served, required
    filename_pattern  (str): The optional regex pattern of served data files
    use_cache        (bool): Cache read data in memory
    is_dpdd          (bool): File are already in DPDD-format.  No translation.

    Attributes
    ----------
    base_dir          (str): The directory of data files being served

    Notes
    -----
    """
    # pylint: disable=too-many-instance-attributes

    def _subclass_init(self, **kwargs):
        self.base_dir = kwargs['base_dir']
        self._filename_re = re.compile(kwargs.get('filename_pattern', FILE_PATTERN))
        self.use_cache = bool(kwargs.get('use_cache', True))

        if not os.path.isdir(self.base_dir):
            raise ValueError('`base_dir` {} is not a valid directory'.format(self.base_dir))

        _schema_filename = kwargs.get('schema_filename', SCHEMA_FILENAME)
        # If _schema_filename is an absolute path, os.path.join will just return _schema_filename
        self._schema_path = os.path.join(self.base_dir, _schema_filename)

        self._schema = None
        if self._schema_path and os.path.isfile(self._schema_path):
            self._schema = self._generate_schema_from_yaml(self._schema_path)

        self._file_handles = dict()
        self._datasets = self._generate_datasets()
        if not self._datasets:
            err_msg = 'No catalogs were found in `base_dir` {}'
            raise RuntimeError(err_msg.format(self.base_dir))

        if not self._schema:
            warnings.warn('Falling back to reading all datafiles for column names')
            self._schema = self._generate_schema_from_datafiles(self._datasets)

        if kwargs.get('is_dpdd'):
            self._quantity_modifiers = {col: None for col in self._schema}
        else:
            if any(col.endswith('_fluxSigma') for col in self._schema):
                dm_schema_version = 1
            elif any(col.endswith('_fluxErr') for col in self._schema):
                dm_schema_version = 2
            else:
                dm_schema_version = 3

            self._quantity_modifiers = self._generate_modifiers(dm_schema_version)

        self._quantity_info_dict = self._generate_info_dict(META_PATH)
        self._native_filter_quantities = self._generate_native_quantity_list()

    @staticmethod
    def _generate_modifiers(**kwargs):
        """Creates a dictionary relating native and homogenized column names

        Args:
            dm_schema_version (int): DM schema version (1, 2, or 3)

        Returns:
            A dictionary of the form {<homogenized name>: <native name>, ...}
        """
        flux_name = 'flux' if dm_schema_version <= 2 else 'instFlux'
        flux_err_name = 'Sigma' if dm_schema_version <= 1 else 'Err'

        modifiers = {
            'diaSourceId': 'id',
            'parentDiaSourceId': 'parent',
#            'midPointTai': 'dateobs'?  I don't know what this is called
            'ra': (np.rad2deg, 'coord_ra'),
            'dec': (np.rad2deg, 'coord_dec'),
            'x': 'slot_Centroid_x',
            'y': 'slot_Centroid_y',
            'xErr': 'slot_Centroid_xErr',
            'yErr': 'slot_Centroid_yErr',
            'apFlux': 'slot_ApFlux_instFlux',
            'apFluxErr': 'slot_ApFlux_instFluxErr',
#           'snr': ''?  Doesn't have to be apflux/apFluxErr.  Detection could be different.  What is this called?
            'psFlux': 'slot_PsfFlux_instFlux',
            'psFluxErr': 'slot_PsfFlux_instFluxErr',
            'dipAngle': 'ip_diffim_DipoleFit_orientation',
            'dipChi2': 'ip_diffim_DipoleFit_chi2dof',
            'totFlux': 'ip_diffim_forced_PsfFlux_instFlux',
            'totFluxErr': 'ip_diffim_forced_PsfFlux_instFluxErr',
            'isDipole': 'ip_diffim_DipoleFit_flag_classification',
            'ixyPSF': 'slot_PsfShape_xy',
            'filter': 'filter',
            'xy_flag': 'slot_Centroid_flag',
            'sky': (convert_flux_to_nanoJansky,
                    'base_LocalBackground_{}'.format(flux_name),
                    'fluxmag0'),
            'skyErr': (convert_flux_to_nanoJansky,
                       'base_LocalBackground_{}{}'.format(flux_name, flux_err_name),
                       'fluxmag0'),
            'sky_flag': 'base_LocalBackground_flag',
            'I_flag': 'slot_Shape_flag',
            'Ixx': 'slot_Shape_xx',
            'IxxPSF': 'slot_PsfShape_xx',
            'Iyy': 'slot_Shape_yy',
            'IyyPSF': 'slot_PsfShape_yy',
            'Ixy': 'slot_Shape_xy',
            'IxyPSF': 'slot_PsfShape_xy',
            'mag': 'mag',
            'magerr': 'mag_err',
            'fluxmag0': 'fluxmag0',
            'apFlux_flag': 'slot_ApFlux_flag',
            'psFlux_flag': 'slot_PsfFlux_flag',
            'psNdata': 'slot_PsfFlux_area',
            # There are no 'slot_*' values for the extendedness and blendedness
            # in the Run 1.2i processing (as of 2019-03-05)
            'extendedness': 'base_ClassificationExtendedness_value',
        }

        not_good_flags = (
            'base_PixelFlags_flag_edge',
            'base_PixelFlags_flag_interpolatedCenter',
            'base_PixelFlags_flag_saturatedCenter',
            'base_PixelFlags_flag_crCenter',
            'base_PixelFlags_flag_bad',
            'base_PixelFlags_flag_suspectCenter',
        )

        modifiers['good'] = (create_basic_flag_mask,) + not_good_flags
        modifiers['clean'] = (
            create_basic_flag_mask,
            'deblend_skipped',
        ) + not_good_flags

        return modifiers
