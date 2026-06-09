"""
Configuration Validator

Validates credentials, environment variables, and tool schema completeness.
Ensures system is properly configured before running.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ConfigurationValidator:
    """Validates system configuration."""
    
    def __init__(self):
        """Initialize validator."""
        self.errors = []
        self.warnings = []
        self.info = []
        self.validation_time = datetime.now().isoformat()
    
    def validate_env_variable(self, var_name, required=True):
        """Validate an environment variable."""
        value = os.environ.get(var_name)
        
        if not value:
            if required:
                self.errors.append(f"Missing required environment variable: {var_name}")
            else:
                self.warnings.append(f"Optional environment variable not set: {var_name}")
            return False
        else:
            # Check if it looks like it has actual content (not just placeholder)
            if len(value) < 5:
                self.warnings.append(f"Environment variable {var_name} has suspiciously short value")
            else:
                self.info.append(f"✓ Environment variable {var_name} is set")
            return True
    
    def validate_credentials_file(self, cred_path=None):
        """Validate credentials file exists and is readable."""
        if not cred_path:
            cred_path = os.path.expanduser("~/.config/helix/credentials.env")
        
        if not os.path.exists(cred_path):
            self.warnings.append(f"Credentials file not found: {cred_path}")
            return False
        
        if not os.access(cred_path, os.R_OK):
            self.errors.append(f"Credentials file not readable: {cred_path}")
            return False
        
        self.info.append(f"✓ Credentials file readable: {cred_path}")
        
        # Try to parse it
        try:
            with open(cred_path, 'r') as f:
                lines = f.readlines()
                var_count = 0
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        var_count += 1
                
                if var_count == 0:
                    self.warnings.append("Credentials file appears to be empty")
                else:
                    self.info.append(f"✓ Credentials file contains {var_count} variables")
            
            return True
        except Exception as e:
            self.errors.append(f"Error reading credentials file: {e}")
            return False
    
    def validate_required_credentials(self):
        """Validate all required credentials are set."""
        required_creds = {
            # No credentials are strictly required — Helix runs with dashboard only
        }
        
        optional_creds = {
            "GEMINI_API_KEY": "Google Gemini API key",
            "ANTHROPIC_API_KEY": "Anthropic API key",
            "HELIX_TELEGRAM_TOKEN": "Telegram bot token",
            "GITHUB_TOKEN": "GitHub API token",
            "MOLTBOOK_API_KEY": "MoltBook API key",
        }
        
        print("\n[CREDENTIALS VALIDATION]")
        print("  Required credentials:")
        for cred, desc in required_creds.items():
            if os.environ.get(cred):
                self.info.append(f"✓ {cred}: {desc}")
                print(f"    ✓ {cred}")
            else:
                self.errors.append(f"Missing required credential: {cred}")
                print(f"    ✗ {cred} (MISSING)")
        
        print("\n  Optional credentials:")
        for cred, desc in optional_creds.items():
            if os.environ.get(cred):
                self.info.append(f"✓ {cred}: {desc}")
                print(f"    ✓ {cred}")
            else:
                self.warnings.append(f"Optional credential not set: {cred}")
                print(f"    - {cred} (not set)")
    
    def validate_data_directories(self):
        """Validate required data directories."""
        required_dirs = [
            "data",
            "data/memory",
            "data/beliefs",
            "data/spatial",
            "logs",
            "journals"
        ]
        
        print("\n[DATA DIRECTORIES VALIDATION]")
        for dir_path in required_dirs:
            full_path = os.path.join(os.getcwd(), dir_path)
            
            if os.path.isdir(full_path):
                self.info.append(f"✓ Directory exists: {dir_path}")
                print(f"  ✓ {dir_path}")
            else:
                self.warnings.append(f"Directory will be created by setup.py: {dir_path}")
                print(f"  - {dir_path} (will be created by setup.py)")
    
    def validate_tool_schema(self, schema_path=None):
        """Validate tool schema file."""
        if not schema_path:
            schema_path = os.path.join(os.getcwd(), "data/tool_schemas.json")
        
        print("\n[TOOL SCHEMA VALIDATION]")
        
        if not os.path.exists(schema_path):
            self.warnings.append(f"Tool schema file not found: {schema_path}")
            print(f"  - Tool schema file will be generated at runtime")
            return False
        
        try:
            with open(schema_path, 'r') as f:
                schema = json.load(f)
            
            tool_count = len(schema.get("tools", []))
            
            if tool_count == 0:
                self.warnings.append("Tool schema file appears to be empty")
                print(f"  - Tool schema is empty (tools will be loaded from system)")
            else:
                self.info.append(f"✓ Tool schema contains {tool_count} tools")
                print(f"  ✓ Tool schema valid with {tool_count} tools")
            
            # Validate each tool has required fields
            invalid_tools = []
            for tool in schema.get("tools", []):
                if not all(k in tool for k in ["name", "description", "parameters"]):
                    invalid_tools.append(tool.get("name", "unknown"))
            
            if invalid_tools:
                self.errors.append(f"Invalid tool definitions: {invalid_tools}")
                print(f"  ✗ Invalid tool definitions found")
            
            return tool_count > 0
        except json.JSONDecodeError as e:
            self.errors.append(f"Tool schema JSON is invalid: {e}")
            print(f"  ✗ Tool schema JSON parsing failed")
            return False
        except Exception as e:
            self.errors.append(f"Error reading tool schema: {e}")
            return False
    
    def validate_python_dependencies(self):
        """Validate required Python packages."""
        required_packages = {
            "dotenv": "python-dotenv",
            "google": "google-generativeai",
            "psutil": "psutil",
        }
        
        print("\n[PYTHON DEPENDENCIES VALIDATION]")
        
        missing_packages = []
        for module_name, package_name in required_packages.items():
            try:
                __import__(module_name)
                self.info.append(f"✓ Package available: {package_name}")
                print(f"  ✓ {package_name}")
            except ImportError:
                missing_packages.append(package_name)
                self.warnings.append(f"Optional package not installed: {package_name}")
                print(f"  - {package_name} (not installed)")
        
        return len(missing_packages) == 0
    
    def get_report(self):
        """Generate validation report."""
        return {
            "validation_time": self.validation_time,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "is_valid": len(self.errors) == 0
        }
    
    def print_summary(self):
        """Print validation summary."""
        report = self.get_report()
        
        print("\n" + "=" * 70)
        print("CONFIGURATION VALIDATION SUMMARY")
        print("=" * 70)
        
        print(f"\nValidation Time: {self.validation_time}")
        print(f"Status: {'✓ VALID' if report['is_valid'] else '✗ INVALID'}")
        
        print(f"\nErrors: {len(self.errors)}")
        for error in self.errors:
            print(f"  ✗ {error}")
        
        print(f"\nWarnings: {len(self.warnings)}")
        for warning in self.warnings:
            print(f"  ⚠ {warning}")
        
        print(f"\nInfo: {len(self.info)}")
        for info in self.info[:10]:  # Show first 10
            print(f"  {info}")
        
        if len(self.info) > 10:
            print(f"  ... and {len(self.info) - 10} more")
        
        print("\n" + "=" * 70)


def run_full_validation():
    """Run full configuration validation."""
    validator = ConfigurationValidator()
    
    print("=" * 70)
    print("HELIX CONFIGURATION VALIDATOR")
    print("=" * 70)
    
    # Validate credentials file
    validator.validate_credentials_file()
    
    # Validate required credentials
    validator.validate_required_credentials()
    
    # Validate data directories
    validator.validate_data_directories()
    
    # Validate tool schema
    validator.validate_tool_schema()
    
    # Validate dependencies
    validator.validate_python_dependencies()
    
    # Print summary
    validator.print_summary()
    
    # Return success/failure
    report = validator.get_report()
    return report["is_valid"]


if __name__ == "__main__":
    success = run_full_validation()
    sys.exit(0 if success else 1)
