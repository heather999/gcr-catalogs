import os
import importlib
import warnings
import yaml
import requests
from GCR import BaseGenericCatalog


__all__ = ['has_catalog', 'get_catalog_config', 'get_available_catalogs', 'load_catalog']

_CONFIG_DIRNAME = 'catalog_configs'
_GITHUB_URL = 'https://raw.githubusercontent.com/LSSTDESC/gcr-catalogs/master/GCRCatalogs'
_YAML_EXTENSIONS = ('.yaml', '.yml')


def load_yaml_local(yaml_file):
    with open(yaml_file) as f:
        return yaml.safe_load(f)


def load_yaml(yaml_file):
    """
    Load *yaml_file*. Ruturn a dictionary.
    """
    try:
        r = requests.get(yaml_file, stream=True)
    except (requests.exceptions.MissingSchema, requests.exceptions.URLRequired):
        config = load_yaml_local(yaml_file)
    else:
        if r.status_code == 404:
            raise requests.RequestException('404 Not Found!')
        r.raw.decode_content = True
        config = yaml.safe_load(r.raw)
    return config


class Config():
    def __init__(self, config_path, config_dir=''):
        self.path = os.path.join(config_dir, config_path)
        self.basename = os.path.basename(self.path)
        self.rootname, self.ext = os.path.splitext(self.basename)
        self.name = self.rootname.lower()
        self._content = None

    @property
    def ignore(self):
        return (
            self.rootname.startswith('_') or
            self.ext.lower() not in _YAML_EXTENSIONS
        )

    @property
    def content(self):
        if self._content is None:
            self._content = load_yaml_local(self.path)
        return self._content


class ConfigRegister():
    def __init__(self, config_dir):
        self._config_dir = config_dir
        self._configs = dict()
        self._configs_resolved = dict()

        for config_file in os.listdir(self._config_dir):
            config = Config(config_file, self._config_dir)
            if not config.ignore:
                self._configs[config.name] = config

    @staticmethod
    def normalize_name(name):
        name = str(name).lower()
        for extension in _YAML_EXTENSIONS:
            if name.endswith(extension):
                return name[:-len(extension)]
        return name

    def get_raw(self, name):
        name = self.normalize_name(name)
        if name not in self._configs:
            raise KeyError('Catalog {} does not exist.'.format(name))
        return self._configs[name].content

    def resolve_config(self, config, past_refs=None):
        for key in ('alias', 'based_on'):
            if config.get(key):
                base_name = self.normalize_name(config[key])
                base_config = self.get_raw(base_name)

                if past_refs is None:
                    past_refs = [base_name]
                elif base_name in past_refs:
                    raise RecursionError('Recursive reference')
                else:
                    past_refs.append(base_name)

                if key == 'based_on':
                    config = config.copy()
                    del config[key]
                    base_config = base_config.copy()
                    base_config.update(config)

                return self.resolve_config(base_config, past_refs)

        return config

    def get_resolved(self, name):
        name = self.normalize_name(name)
        if name not in self._configs_resolved:
            self._configs_resolved[name] = self.resolve_config(self.get_raw(name), [name])
        config = self._configs_resolved[name]
        if 'subclass_name' not in config:
            raise ValueError('`subclass_name` is missing in the config of {}'
                             'and its dependencies'.format(name))
        return config

    def online_alias_check(self, name):
        config = self.get_raw(name)
        if config.get('alias'):
            name = self.normalize_name(name)
            url = '/'.join((_GITHUB_URL, _CONFIG_DIRNAME, self._configs[name].basename))
            try:
                online_config = load_yaml(url)
            except (requests.RequestException, yaml.error.YAMLError):
                pass
            else:
                if config['alias'] != online_config.get('alias'):
                    warnings.warn('`{}` is currently an alias of `{}`.'
                    'Please be advised that it will soon change to point to an updated version `{}`.'
                    'The updated version is already available in the master branch.'.format(
                        name,
                        config['alias'],
                        online_config.get('alias'),
                    ))

    def __contains__(self, key):
        return (self.normalize_name(key) in self._configs)

    @property
    def catalog_configs(self):
        return {v.rootname: v.content for v in self._configs.values()}

    @property
    def default_catalog_configs(self):
        return {
            v.rootname: self.get_resolved(v.name) for v in self._configs.values()
            if v.content.get('include_in_default_catalog_list')
        }

    @property
    def catalog_list(self):
        return sorted((v.rootname for v in self._configs.values()))

    @property
    def default_catalog_list(self):
        return sorted((
            v.rootname for v in self._configs.values()
            if v.content.get('include_in_default_catalog_list')
        ))

    @property
    def reader_list(self):
        return sorted(set((self.get_resolved(k)['subclass_name'] for k in self._configs)))


def import_subclass(subclass_path, package=None, required_base_class=None):
    """
    Import and return a subclass.
    *subclass_path* must be in the form of 'module.subclass'.
    """
    module, _, subclass_name = subclass_path.rpartition('.')
    if package and not module.startswith('.'):
        module = '.' + module
    subclass = getattr(importlib.import_module(module, package), subclass_name)
    if required_base_class and not issubclass(subclass, required_base_class):
        raise ValueError("Provided class is not a subclass of *required_base_class*")
    return subclass


def load_catalog_from_config_dict(catalog_config):
    """
    Load a galaxy catalog using a config dictionary.

    Parameters
    ----------
    catalog_config : dict
        a dictionary of config options

    Return
    ------
    galaxy_catalog : instance of a subclass of BaseGalaxyCatalog

    See also
    --------
    load_catalog()
    """
    return import_subclass(catalog_config['subclass_name'],
                           __package__,
                           BaseGenericCatalog)(**catalog_config)


def get_available_catalogs(include_default_only=True, names_only=False):
    """
    Return available catalogs as a dictionary,
    or a list (when *names_only* set to True).

    If *include_default_only* is set to False, return all catalogs.
    If *names_only* is set to False, return catalog name and associated configs
    """
    if names_only:
        if include_default_only:
            return _config_register.default_catalog_list
        return _config_register.catalog_list

    if include_default_only:
        return _config_register.default_catalog_configs
    return _config_register.catalog_configs


def get_reader_list():
    """
    Returns a list of readers
    """
    return _config_register.reader_list


def get_catalog_config(catalog_name, raw_config=False):
    """
    Returns the config dict of *catalog_name*.
    If *raw_config* set to `True`, do not resolve references (alias, based_on)
    """
    if raw_config:
        return _config_register.get_raw(catalog_name)
    return _config_register.get_resolved(catalog_name)


def has_catalog(catalog_name):
    """
    Check if *catalog_name* exists
    """
    return catalog_name in _config_register


def load_catalog(catalog_name, config_overwrite=None):
    """
    Load a galaxy catalog as specified in one of the yaml file in catalog_configs.

    Parameters
    ----------
    catalog_name : str
        name of the catalog (without '.yaml')
    config_overwrite : dict, optional
        a dictionary of config options to overwrite

    Return
    ------
    galaxy_catalog : instance of a subclass of BaseGalaxyCatalog
    """
    _config_register.online_alias_check(catalog_name)
    config = _config_register.get_resolved(catalog_name)
    if config_overwrite:
        if any(key in config_overwrite for key in ('alias', 'based_on')):
            raise ValueError('`config_overwrite` cannot specify `alias` or `based_on`!')
        config = config.copy()
        config.update(config_overwrite)
    return load_catalog_from_config_dict(config)

_config_register = ConfigRegister(os.path.join(os.path.dirname(__file__), _CONFIG_DIRNAME))
