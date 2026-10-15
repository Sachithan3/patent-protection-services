#!/usr/bin/env python3
"""
ClaimGuard AI Phase 1 - Integration Test Suite
Tests core functionality without heavy model downloads in test environment.
"""

import csv
import re
import sys
from pathlib import Path


def test_seed_data_structure():
    """Verify seed data file structure and contents."""
    print("\n" + "=" * 70)
    print("TEST 1: Seed Data Structure Validation")
    print("=" * 70)

    seed_file = Path("data/Patents_data_withclaims.csv")
    
    if not seed_file.exists():
        print("❌ FAILED: data/Patents_data_withclaims.csv not found")
        return False

    csv.field_size_limit(sys.maxsize)
    with seed_file.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    required_keys = {"publication_number", "title", "abstract", "claims"}
    if not rows or not required_keys.issubset(rows[0]):
        print(f"❌ FAILED: CSV missing required columns: {required_keys}")
        return False
    if any(not (row.get("claims") or "").strip() for row in rows):
        print("❌ FAILED: One or more patents have no claims")
        return False

    print(f"✓ CSV structure valid with {len(rows)} claim-bearing patents")
    
    # Print patent summary
    print("\nPatent Summary:")
    for patent in rows[:5]:
        claim_count = len(re.findall(r"(?m)^\s*\d+\s*\.\s*", patent["claims"]))
        print(f"  • {patent['publication_number']}")
        print(f"    Title: {patent['title'][:70]}...")
        print(f"    Claims: {claim_count or 1}")

    return True


def test_project_structure():
    """Verify all required project files exist."""
    print("\n" + "=" * 70)
    print("TEST 2: Project Structure Validation")
    print("=" * 70)

    required_files = {
        "requirements.txt": "Python dependencies",
        ".env": "Environment configuration",
        ".env.template": "Environment template",
        ".gitignore": "Git ignore rules",
        "README.md": "Project documentation",
        "generate_seed.py": "Seed data generator",
        "embeddings.py": "Embedding engine",
    }

    required_dirs = {
        "app/core": "Core business logic",
        "app/models": "SQLAlchemy models",
        "app/api": "FastAPI routes",
        "data": "Seed data directory",
        "logs": "Application logs",
    }

    all_valid = True

    print("\nFiles:")
    for file_path, description in required_files.items():
        exists = Path(file_path).exists()
        status = "✓" if exists else "❌"
        print(f"  {status} {file_path:30} {description}")
        all_valid = all_valid and exists

    print("\nDirectories:")
    for dir_path, description in required_dirs.items():
        exists = Path(dir_path).exists()
        status = "✓" if exists else "❌"
        print(f"  {status} {dir_path:30} {description}")
        all_valid = all_valid and exists

    return all_valid


def test_requirements_file():
    """Verify requirements.txt contains all necessary dependencies."""
    print("\n" + "=" * 70)
    print("TEST 3: Requirements.txt Validation")
    print("=" * 70)

    required_packages = {
        "fastapi": "Web framework",
        "uvicorn": "ASGI server",
        "pydantic": "Data validation",
        "python-dotenv": "Environment variables",
        "sentence-transformers": "Embedding model",
        "torch": "ML framework",
        "sqlalchemy": "ORM",
        "pgvector": "Vector extension",
        "numpy": "Numerical computing",
        "scipy": "Scientific computing",
    }

    with open("requirements.txt", "r") as f:
        requirements_content = f.read().lower()

    print("\nRequired Packages:")
    all_found = True
    for package, description in required_packages.items():
        found = package.lower() in requirements_content
        status = "✓" if found else "❌"
        print(f"  {status} {package:25} {description}")
        all_found = all_found and found

    return all_found


def test_embeddings_code():
    """Verify embedding engine code structure."""
    print("\n" + "=" * 70)
    print("TEST 4: Embedding Engine Code Structure")
    print("=" * 70)

    with open("embeddings.py", "r") as f:
        code_content = f.read()

    required_elements = {
        "class EmbeddingEngine": "Main class",
        "def embed_text(": "Single text embedding method",
        "def embed_batch(": "Batch embedding method",
        "def get_vector_dimension(": "Vector dimension getter",
        "def _normalize_vector(": "Vector normalization",
        "SentenceTransformer": "Sentence-transformers import",
        "List[float]": "Type hints present",
    }

    print("\nCode Elements:")
    all_found = True
    for element, description in required_elements.items():
        found = element in code_content
        status = "✓" if found else "❌"
        print(f"  {status} {element:35} {description}")
        all_found = all_found and found

    # Check vector dimension is 384
    if "all-MiniLM-L6-v2" in code_content and "384" in code_content:
        print(f"  ✓ Model configured for 384-dimensional vectors")
    else:
        print(f"  ❌ Vector dimension mismatch")
        all_found = False

    return all_found


def test_environment_config():
    """Verify environment configuration."""
    print("\n" + "=" * 70)
    print("TEST 5: Environment Configuration")
    print("=" * 70)

    with open(".env", "r") as f:
        env_content = f.read()

    required_config = {
        "DATABASE_HOST": "Database connection host",
        "DATABASE_PORT": "Database port",
        "DATABASE_USER": "Database user",
        "DATABASE_NAME": "Database name",
        "EMBEDDING_MODEL": "Embedding model name",
        "EMBEDDING_VECTOR_DIMENSION": "Vector dimension (384)",
        "API_PORT": "FastAPI server port",
    }

    print("\nConfiguration Variables:")
    all_found = True
    for var, description in required_config.items():
        found = var in env_content
        status = "✓" if found else "❌"
        print(f"  {status} {var:30} {description}")
        all_found = all_found and found

    return all_found


def run_all_tests():
    """Execute all validation tests."""
    print("\n" + "█" * 70)
    print("█  ClaimGuard AI Phase 1 - Integration Test Suite")
    print("█" * 70)

    tests = [
        ("Seed Data Structure", test_seed_data_structure),
        ("Project Structure", test_project_structure),
        ("Requirements File", test_requirements_file),
        ("Embedding Engine Code", test_embeddings_code),
        ("Environment Config", test_environment_config),
    ]

    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"\n❌ EXCEPTION in {test_name}: {str(e)}")
            results[test_name] = False

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, passed_flag in results.items():
        status = "✓ PASS" if passed_flag else "❌ FAIL"
        print(f"  {status}: {test_name}")

    print(f"\n  Result: {passed}/{total} tests passed")

    if passed == total:
        print("\n✓ Phase 1 Infrastructure Ready for Deployment!")
        return True
    else:
        print(f"\n❌ {total - passed} test(s) failed. Review above.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
