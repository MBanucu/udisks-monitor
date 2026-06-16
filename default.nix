{
  lib
, buildPythonPackage
, setuptools
, src
, udisks2
, dosfstools
, strip-ansi
, unittestCheckHook
}:

buildPythonPackage rec {
  pname = "udisks-monitor";
  version = "0.2.0";
  pyproject = true;

  inherit src;

  nativeBuildInputs = [ setuptools ];
  nativeCheckInputs = [ dosfstools unittestCheckHook ];
  propagatedBuildInputs = [ strip-ansi udisks2 ];

  unittestFlagsArray = [ "-s" "tests" "-v" ];
  pythonImportsCheck = [ "udisks_monitor" ];

  meta = with lib; {
    description = "Event-driven pub/sub wrapper around udisksctl monitor (Linux)";
    homepage = "https://github.com/MBanucu/udisks-monitor";
    license = licenses.gpl3Only;
    maintainers = [ ];
  };
}