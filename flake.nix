{
  description = "Application packaged using poetry2nix";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        # see https://github.com/nix-community/poetry2nix/tree/master#api for more functions and examples.
        pkgs = nixpkgs.legacyPackages.${system};
        inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication;
      in
      {
        packages = {
          ygg-map = mkPoetryApplication { projectDir = self; };
          default = self.packages.${system}.ygg-map;
        };

        nixosModules = {
          ygg-map = { config, lib, pkgs, ... }:
            let
              cfg = config.services.ygg-map;
              package = cfg.package;
              inherit (lib) mkIf mkOption mkEnableOption mdDoc;
            in
            {
              options.services.ygg-map = {
                enable = mkEnableOption (mdDoc "the yggdrasil map service");

                package = mkOption {
                  type = types.package;
                  default = pkgs.ygg-map;
                  defaultText = literalExpression "pkgs.ygg-map";
                  description = mdDoc "Yggdrasil map package to use.";
                };

                http = {
                  host = mkOption {
                    type = types.either types.str (types.listOf types.str);
                    default = [
                      "::"
                    ];
                    example = "::1";
                    description = mdDoc "Only listen to incoming requests on specific IP/host.";
                  };

                  port = mkOption {
                    default = 10200;
                    type = types.port;
                    description = mdDoc "The port on which to listen.";
                  };
                };

                openFirewall = mkOption {
                  default = false;
                  type = types.bool;
                  description = lib.mdDoc "Whether to open the firewall for the specified port.";
                };
              };
              config = mkIf cfg.enable (
                let
                  
                in
                {
                  networking.firewall.allowedTCPPorts = mkIf cfg.openFirewall [ cfg.http.port ];
                  systemd.services.ygg-map = {
                    description = "Yggdrasil map";
                    after = [
                      "yggdrasil.service"
                    ];

                    environment.PYTHONPATH = package.pythonPath;
                    serviceConfig = {
                      # ExecStart = "${package}/bin/hass --config '${cfg.configDir}'";
                      Restart = "on-failure";
                      KillSignal = "SIGINT";

                    };
                  };
                }
              );
            };
          default = self.nixosModules.${system}.ygg-map;
        };

        devShells.default = pkgs.mkShell {
          inputsFrom = [ self.packages.${system}.ygg-map ];
          packages = [ pkgs.poetry ];
        };
      });
}
