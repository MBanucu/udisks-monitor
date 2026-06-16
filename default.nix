{
  lib
, buildPythonPackage
, setuptools
, src
}:
buildPythonPackage rec {
  pname = "udisks-monitor";
  version = "0.1.0";
  pyproject = true;

  inherit src;

  nativeBuildInputs = [ setuptools ];
  propagatedBuildInputs = [ ];

  doCheck = false;
  pythonImportsCheck = [ "udisks_monitor" ];

  meta = with lib; {
    description = "Event-driven pub/sub wrapper around udisksctl monitor (Linux)";
    homepage = "https://github.com/MBanucu/udisks-monitor";
    license = licenses.gpl3Only;
    maintainers = with maintainers; [ ];
  };
}
