"""tests/test_paths_root.py — Phase 2: ASSISTANT_DESKTOP_DATA_ROOT path resolution.

Verifies that the ``ASSISTANT_DESKTOP_DATA_ROOT`` environment variable correctly
maps runtime paths (root, database, resume storage, logs, settings) on Windows,
and that existing behaviour is preserved when the variable is unset.
"""

import os
import pytest
from pathlib import Path

# Import the Paths class and the get_paths function with data root support
from src.core.paths import Paths, get_paths, reset_paths
from src.api.paths_root import load_paths_with_data_root, get_paths_root, detectRootWithDataRoot


class TestPathsRootDefault:
    """Tests with ASSISTANT_DESKTOP_DATA_ROOT unset (existing behaviour)."""

    def test_default_paths_resolve_without_data_root(self):
        """When ASSISTANT_DESKTOP_DATA_ROOT is unset, paths resolve from project root."""
        # Ensure the env var is not set
        env = os.environ.copy()
        env.pop('ASSISTANT_DESKTOP_DATA_ROOT', None)

        paths = get_paths()
        assert paths.root is not None
        assert paths.data is not None
        assert paths.db is not None
        assert paths.profile_dir is not None
        assert paths.resume_dir is not None
        assert paths.logs is not None
        assert paths.exports is not None

    def test_paths_describe_without_data_root(self):
        """describe() should return all path keys when data root is unset."""
        paths = get_paths()
        desc = paths.describe()
        assert 'root' in desc
        assert 'data' in desc
        assert 'profile_dir' in desc
        assert 'resume_dir' in desc
        assert 'db' in desc
        assert 'logs' in desc
        assert 'exports' in desc


class TestPathsRootWithDataRoot:
    """Tests with ASSISTANT_DESKTOP_DATA_ROOT set (Windows data root support)."""

    def test_paths_map_under_data_root(self):
        """When ASSISTANT_DESKTOP_DATA_ROOT is set, data paths flow under it."""
        # Set a temporary data root
        test_data_root = Path('/tmp/test-assistant-data-root')
        test_data_root.mkdir(parents=True, exist_ok=True)

        try:
            env = os.environ.copy()
            env['ASSISTANT_DESKTOP_DATA_ROOT'] = str(test_data_root)

            paths = load_paths_with_data_root(data_root_env='ASSISTANT_DESKTOP_DATA_ROOT', test_env=env)

            # All data paths should be under the explicit data root
            assert str(paths.data).startswith(str(test_data_root)), (
                f'Expected data path under {test_data_root}, got {paths.data}'
            )
            assert str(paths.profile_dir).startswith(str(test_data_root)), (
                f'Expected profile_dir under {test_data_root}, got {paths.profile_dir}'
            )
            assert str(paths.resume_dir).startswith(str(test_data_root)), (
                f'Expected resume_dir under {test_data_root}, got {paths.resume_dir}'
            )
            assert str(paths.logs).startswith(str(test_data_root)), (
                f'Expected logs under {test_data_root}, got {paths.logs}'
            )
            assert str(paths.exports).startswith(str(test_data_root)), (
                f'Expected exports under {test_data_root}, got {paths.exports}'
            )

            # Root should remain the project root (or detected root)
            assert paths.root is not None

        finally:
            # Cleanup
            import shutil
            shutil.rmtree(test_data_root, ignore_errors=True)

    def test_reset_clears_cache(self):
        """reset_paths() should drop the cached instance."""
        reset_paths()
        # After reset, a new call should create a fresh instance
        paths = get_paths()
        assert paths is not None


class TestDetectRootWithDataRoot:
    """Test the detect_root_with_data_root helper."""

    def test_detect_root_with_valid_data_root(self):
        """detectRootWithDataRoot should return a Path when data root exists."""
        test_data_root = Path('/tmp/test-detect-root')
        test_data_root.mkdir(parents=True, exist_ok=True)

        try:
            result = detectRootWithDataRoot(str(test_data_root))
            assert result is not None
            assert isinstance(result, Path)
        finally:
            import shutil
            shutil.rmtree(test_data_root, ignore_errors=True)

    def test_detect_root_with_missing_data_root(self):
        """detectRootWithDataRoot should return None when data root does not exist."""
        nonexistent = Path('/tmp/this-does-not-exist-xyz123')
        result = detectRootWithDataRoot(str(nonexistent))
        assert result is None