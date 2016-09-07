Vagrant.configure(2) do |config|
  config.vm.box = "centos/6"
  config.vm.define "ab-deployment-tool"

  config.vm.provider :virtualbox do |v|
    v.memory = 512
    v.cpus = 2
  end
  
  config.vm.synced_folder ".", "/home/vagrant/sync", disabled: true
  config.vm.synced_folder ".", "/home/vagrant/project", type: "virtualbox"

  config.vm.provision :shell, inline: "sudo yum install epel-release -y; sudo yum install python-pip -y"
end
