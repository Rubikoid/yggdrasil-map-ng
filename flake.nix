{
  description = "Yggdrasil map";

  inputs = {
    # flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, poetry2nix }:
    let
      systems = [
        "x86_64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
    in
    {
      nixosModules = forAllSystems (system: {
        ygg-map = { config, lib, pkgs, ... }:
          let
            cfg = config.services.ygg-map;
            package = cfg.package;
            inherit (lib) mkIf mkOption mkEnableOption mdDoc literalExpression types;
          in
          {
            options.services.ygg-map = {
              enable = mkEnableOption (mdDoc "the yggdrasil map service");

              package = mkOption {
                type = types.package;
                default = self.packages.${system}.ygg-map;
                defaultText = literalExpression "pkgs.ygg-map";
                description = mdDoc "Yggdrasil map package to use.";
              };

              http = {
                host = mkOption {
                  type = types.str;
                  default = "127.0.0.1";
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
                description = mdDoc "Whether to open the firewall for the specified port.";
              };

              extraArgs = mkOption {
                type = types.listOf types.str;
                default = [ ];
                example = [ ];
                description = mdDoc "Extra cmd for ";
              };
            };
            config = mkIf cfg.enable (
              let

              in
              {
                services.yggdrasil.settings = {
                  LogLookups = true;
                };
                networking.firewall.allowedTCPPorts = mkIf cfg.openFirewall [ cfg.http.port ];
                systemd.services.ygg-map = {
                  description = "Yggdrasil map";
                  after = [
                    "yggdrasil.service"
                  ];

                  environment = {
                    SOCKET = "/var/run/yggdrasil/yggdrasil.sock";
                    PYTHONPATH = package.pythonPath;
                  };
                  serviceConfig = {
                    ExecStart = "${package.dependencyEnv}/bin/uvicorn app:app --host ${cfg.http.host} --port ${cfg.http.port} ${lib.strings.escapeShellArgs cfg.extraArgs}";
                    Restart = "on-failure";
                    KillSignal = "SIGINT";
                    # User = "root";
                    # DynamicUser = "yes";
                  };
                };
              }
            );
          };
        default = self.nixosModules.ygg-map;
      });

      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication;
        in
        {
          ygg-map = mkPoetryApplication {
            projectDir = self;
          };
          default = self.packages.${system}.ygg-map;
        });

      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            inputsFrom = [ self.packages.${system}.ygg-map ];
            packages = [ pkgs.poetry ];
          };
        });
    };

  # import ./default.nix {
  #   pkgs = import nixpkgs { inherit system; };
  # }

  # forAllSystems (system:
  #   let

  #   in
  #   {
  #     packages = {
  #       ygg-map = mkPoetryApplication {
  #         projectDir = self;
  #       };
  #       default = self.packages.${system}.ygg-map;
  #     };



  #     devShells.default = pkgs.mkShell {
  #       inputsFrom = [ self.packages.${system}.ygg-map ];
  #       packages = [ pkgs.poetry ];
  #     };
  #   });
}
