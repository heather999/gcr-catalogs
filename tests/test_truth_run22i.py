"""
Tests for  DC2 Truth catalog, Run 2.2i
"""
import os
import pytest
import numpy as np
##from numpy.testing import assert_array_equal
import GCRCatalogs

# pylint: disable=redefined-outer-name
@pytest.fixture(scope='module')
def load_truth_catalog():
    """Convenience function to provide catalog"""
    this_dir = os.path.dirname(__file__)

    reader='dc2_truth_run2.2i_hp9430_million_static_galaxies.yaml'
    
    return GCRCatalogs.load_catalog(reader)

#  Make tests doing some simple queries.  It's hard to imagine anything
#  realistic which doesn't employ some sort of cut.

def test_truth():
    gc = load_truth_catalog()
    print('Catalog loaded')
    galaxies = gc['id']
    res = gc.get_quantities(['id', 'ra', 'flux_r', 'is_pointsource'])
    print('first id: ', res['id'][0])
    print('first ra: ', res['ra'][0])
    print('first flux_r: ', res['flux_r'][0])
    print('first is_pointsource: ', res['is_pointsource'][0])
    print('Found {} galaxies'.format(len(galaxies)))

    for i in range(0,5): print(res['id'][i])

    
    columns =gc.list_all_native_quantities()

    for c in columns: print(c)
    
    #ra = 61.99398718973142
    #de = -32.83695608408115


if __name__== "__main__":
    test_truth()

