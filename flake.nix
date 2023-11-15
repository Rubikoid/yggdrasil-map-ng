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

  outputs =
    { self
    , nixpkgs
    , poetry2nix
      #, flake-utils
    }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forSystems = systems: f:
        nixpkgs.lib.genAttrs systems
          (system: f system (import nixpkgs { inherit system; overlays = [ poetry2nix.overlays.default self.overlays.default ]; }));
      forAllSystems = forSystems supportedSystems;
      projectName = "ygg-map";
    in
    {
      overlays = {
        default = final: prev: {
          ${projectName} = self.packages.${prev.stdenv.hostPlatform.system}.${projectName};
        };
      };

      nixosModules = {
        default = { pkgs, lib, config, ... }: {
          imports = [ ./module.nix ];
          nixpkgs.overlays = [ self.overlays.default ];
        };
      };

      # packages = forAllSystems (system:
      #   import ./default.nix {
      #     pkgs = import nixpkgs { inherit system; };
      #     inherit poetry2nix;
      #   });

      packages = forAllSystems (system: pkgs: {
        default = self.packages.${system}.${projectName};
        ${projectName} = pkgs.poetry2nix.mkPoetryApplication {
          projectDir = self;
          meta.rev = self.dirtyRev or self.rev;
          overrides = pkgs.poetry2nix.overrides.withDefaults (final: prev: {
            ruff = prev.ruff.override { preferWheel = true; };
          });
        };
      });

      devShells = forAllSystems (system: pkgs: {
        default = pkgs.mkShell {
          inputsFrom = [ self.packages.${system}.${projectName} ];
          buildInputs = with pkgs; [ poetry ];
        };
      });

      nixosConfigurations.container = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          ({ pkgs, config, ... }: {
            # Only allow this to boot as a container
            imports = [ self.nixosModules.default ];

            boot.isContainer = true;
            networking.hostName = projectName;

            # Allow nginx through the firewall
            # networking.firewall.allowedTCPPorts = [ http.port ];

            services.${projectName} = {
              enable = true;
              openFirewall = true;
            };

            system.stateVersion = "23.11";
          })
        ];
      };
    };
  # flake-utils.lib.eachDefaultSystem (system:

  # let
  #   pkgs = nixpkgs.legacyPackages.${system};
  #   inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryApplication;
  # in
  # {
  #   packages = {
  #     ygg-map = mkPoetryApplication { projectDir = self; };
  #     default = self.packages.${system}.ygg-map;
  #   };

  #   devShells.default = pkgs.mkShell {
  #     inputsFrom = [ self.packages.${system}.ygg-map ];
  #     packages = [ pkgs.poetry ];
  #   };
  # }
  # );
  # {
  # };
}
