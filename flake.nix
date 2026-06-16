{
  description = "udisks-monitor: Event-driven pub/sub wrapper around udisksctl monitor (Linux)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self
    , nixpkgs
    , flake-utils
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ self.overlays.default ];
        };
      in
      {
        packages.default = pkgs.python3.pkgs.udisks-monitor;

        devShells.default = pkgs.mkShell {
          inputsFrom = [ pkgs.python3.pkgs.udisks-monitor ];
          packages = [ pkgs.python3 ];
          shellHook = ''
            echo "udisks-monitor dev shell. Run tests:"
            echo "  python -m unittest discover -s tests -v"
          '';
        };
      }
    )
    // {
      overlays.default = final: prev: {
        udisks-monitor = (final.python3.pkgs.callPackage ./default.nix {
          src = final.lib.cleanSource ./.;
        }).overrideAttrs (_: {
          doCheck = true;
          installCheckPhase = ''
            runHook preInstallCheck
            python -m unittest discover -s tests -v
            runHook postInstallCheck
          '';
        });
        python3 = prev.python3.override {
          packageOverrides = _: _: {
            inherit (final) udisks-monitor;
          };
        };
      };
    };
}
