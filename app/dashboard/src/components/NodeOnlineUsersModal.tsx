import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Center,
  HStack,
  Icon,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  VStack,
} from "@chakra-ui/react";
import {
  ClockIcon,
  DevicePhoneMobileIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import dayjs from "dayjs";
import { FC } from "react";
import { useQuery } from "react-query";
import { fetch } from "service/http";

type NodeOnlineDevice = {
  device_id: number | null;
  is_legacy: boolean;
  device_model: string | null;
  device_os: string | null;
  ver_os: string | null;
  last_activity_at: string | null;
};

type NodeOnlineUser = {
  user_id: number;
  username: string | null;
  devices: NodeOnlineDevice[];
};

type NodeOnlineUsersResponse = {
  node_id: number;
  available: boolean;
  measured_at: string | null;
  users: NodeOnlineUser[];
};

const deviceLabel = (device: NodeOnlineDevice) => {
  if (device.is_legacy) return "Общий UUID (legacy)";
  const os = [device.device_os, device.ver_os].filter(Boolean).join(" ");
  const label = [device.device_model, os].filter(Boolean).join(" · ");
  return label || `Устройство #${device.device_id ?? "—"}`;
};

export const NodeOnlineUsersModal: FC<{
  nodeId: number;
  nodeName: string;
  isOpen: boolean;
  onClose: () => void;
}> = ({ nodeId, nodeName, isOpen, onClose }) => {
  const { data, isLoading, isError } = useQuery<NodeOnlineUsersResponse>({
    queryKey: ["node-online-users", nodeId],
    queryFn: () => fetch(`/node/${nodeId}/online-users`),
    enabled: isOpen,
    refetchInterval: isOpen ? 10000 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
  });

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="xl" scrollBehavior="inside">
      <ModalOverlay bg="blackAlpha.300" backdropFilter="blur(10px)" />
      <ModalContent mx="3" w="full" maxW="xl">
        <ModalHeader pt={6} pb={4}>
          <HStack spacing={4} align="center">
            <Icon color="primary" w={10} h={10} p={2} borderRadius="lg">
              <UsersIcon color="white" />
            </Icon>
            <Box minW={0}>
              <Text fontSize="lg" fontWeight="semibold">
                Пользователи онлайн
              </Text>
              <Text fontSize="sm" opacity={0.6} mt={1} noOfLines={1} title={nodeName}>
                {nodeName}
              </Text>
            </Box>
          </HStack>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={4}>
          {isLoading ? (
            <Center py={10}><Spinner /></Center>
          ) : isError ? (
            <Alert status="error" borderRadius="md">
              <AlertIcon />
              Не удалось загрузить список пользователей
            </Alert>
          ) : !data?.available ? (
            <Alert status="warning" borderRadius="md">
              <AlertIcon />
              Актуальный снимок недоступен. Данные появятся после следующего сбора статистики.
            </Alert>
          ) : data.users.length === 0 ? (
            <Center py={10} color="gray.500">
              Сейчас на ноде нет активных пользователей
            </Center>
          ) : (
            <VStack spacing={3} align="stretch">
              {data.users.map((user) => (
                <Box
                  key={user.user_id}
                  p={3}
                  border="1px solid"
                  borderColor="gray.200"
                  borderRadius="lg"
                  _dark={{ borderColor: "gray.600" }}
                >
                  <HStack justify="space-between" align="center" mb={2}>
                    <Text fontWeight="semibold" noOfLines={1}>
                      {user.username ?? `Пользователь #${user.user_id}`}
                    </Text>
                    <Badge colorScheme="blue">
                      {user.devices.length}
                      {" "}
                      {user.devices.length === 1 ? "устройство" : "устройства"}
                    </Badge>
                  </HStack>
                  <VStack spacing={2} align="stretch">
                    {user.devices.map((device) => (
                      <Box
                        key={device.device_id ?? "legacy"}
                        px={3}
                        py={2}
                        borderRadius="md"
                        bg="gray.50"
                        _dark={{ bg: "whiteAlpha.100" }}
                      >
                        <HStack align="flex-start" spacing={2}>
                          <Icon as={DevicePhoneMobileIcon} w={4} h={4} mt={0.5} color="blue.500" />
                          <Box minW={0}>
                            <Text fontSize="sm" fontWeight="medium">
                              {deviceLabel(device)}
                            </Text>
                            <HStack mt={1} spacing={1} color="gray.500">
                              <Icon as={ClockIcon} w={3} h={3} />
                              <Text fontSize="xs">
                                {device.last_activity_at
                                  ? `Активность: ${dayjs(device.last_activity_at).format("YYYY-MM-DD HH:mm:ss")}`
                                  : "Время активности неизвестно"}
                              </Text>
                            </HStack>
                          </Box>
                        </HStack>
                      </Box>
                    ))}
                  </VStack>
                </Box>
              ))}
            </VStack>
          )}
        </ModalBody>
        <ModalFooter pt={2}>
          <Text fontSize="xs" color="gray.500" mr="auto">
            Online — недавний трафик, а не открытое TCP-соединение
          </Text>
          <Button size="sm" onClick={onClose}>Закрыть</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
};
